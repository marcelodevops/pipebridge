"""Bounded stash/unstash grammar, token parsing, and Python 3 helper templates."""

from __future__ import annotations

import re

from .findings import PB_LIB_CALL, Finding
from .groovystrings import decode_string
from .lexer import COLON, COMMA, IDENT, LPAREN, NEWLINE, RPAREN, STRING_DQ, STRING_SQ

STASH_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_LITERAL_SEG_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_STRING_LIT_KINDS = (STRING_SQ, STRING_DQ)


def valid_stash_name(name: str) -> bool:
    return STASH_NAME_RE.fullmatch(name) is not None


def valid_stash_glob(pattern: str) -> bool:
    """Validate the bounded Ant-style glob grammar in §11."""
    if not pattern or "\\" in pattern or pattern.startswith("/") or pattern.endswith("/"):
        return False
    for seg in pattern.split("/"):
        if seg in ("", ".", ".."):
            return False
        if seg in ("*", "**"):
            continue
        if _LITERAL_SEG_RE.fullmatch(seg) is None:
            return False
    return True


def parse_stash_tokens(tokens, start_pos: int) -> tuple[tuple[str, str, str | None] | None, int, str | None]:
    """Parse ``stash name: '<lit>', includes: '<glob>'[, excludes: '<glob>']``.

    Returns ``((name, includes, excludes), next_pos, error_reason)``.
    """
    n = len(tokens)
    pos = start_pos
    paren = False
    if pos < n and tokens[pos].kind == LPAREN:
        paren = True
        pos += 1

    expected_keys = ("name", "includes", "excludes")
    parsed: dict[str, str] = {}
    key_idx = 0

    while key_idx < 3:
        while pos < n and tokens[pos].kind == NEWLINE:
            pos += 1
        if pos >= n or tokens[pos].kind != IDENT:
            return None, pos, "stash requires named arguments (name:, includes:, optional excludes:)"
        key = tokens[pos].value
        if key != expected_keys[key_idx]:
            return None, pos, f"stash expected '{expected_keys[key_idx]}:' argument"
        pos += 1
        if pos >= n or tokens[pos].kind != COLON:
            return None, pos, f"stash expected ':' after '{key}'"
        pos += 1
        while pos < n and tokens[pos].kind == NEWLINE:
            pos += 1
        if pos >= n or tokens[pos].kind not in _STRING_LIT_KINDS:
            return None, pos, f"stash '{key}' must be a literal single- or double-quoted string"
        tok = tokens[pos]
        dec = decode_string(tok.value, tok.kind, tok.line, tok.col)
        if dec.has_interpolation or dec.value is None:
            return None, pos, f"stash '{key}' must not contain interpolation"
        parsed[key] = dec.value
        pos += 1
        key_idx += 1

        if pos < n and tokens[pos].kind == COMMA:
            if key_idx >= 3:
                return None, pos, "stash accepts only name, includes, and optional excludes"
            pos += 1
            continue
        break

    if paren:
        while pos < n and tokens[pos].kind == NEWLINE:
            pos += 1
        if pos >= n or tokens[pos].kind != RPAREN:
            return None, pos, "stash call is missing closing ')'"
        pos += 1

    if "name" not in parsed or "includes" not in parsed:
        return None, pos, "stash requires both 'name' and 'includes'"
    name = parsed["name"]
    includes = parsed["includes"]
    excludes = parsed.get("excludes")
    if not valid_stash_name(name):
        return None, pos, f"invalid stash name '{name}'"
    if not valid_stash_glob(includes):
        return None, pos, f"invalid stash includes glob '{includes}'"
    if excludes is not None and not valid_stash_glob(excludes):
        return None, pos, f"invalid stash excludes glob '{excludes}'"
    return (name, includes, excludes), pos, None


def parse_unstash_tokens(tokens, start_pos: int) -> tuple[str | None, int, str | None]:
    """Parse ``unstash '<literal>'`` or ``unstash('<literal>')``."""
    n = len(tokens)
    pos = start_pos
    paren = False
    if pos < n and tokens[pos].kind == LPAREN:
        paren = True
        pos += 1
        while pos < n and tokens[pos].kind == NEWLINE:
            pos += 1
    if pos >= n or tokens[pos].kind not in _STRING_LIT_KINDS:
        return None, pos, "unstash requires a literal single- or double-quoted string name"
    tok = tokens[pos]
    dec = decode_string(tok.value, tok.kind, tok.line, tok.col)
    if dec.has_interpolation or dec.value is None:
        return None, pos, "unstash name must not contain interpolation"
    pos += 1
    if paren:
        while pos < n and tokens[pos].kind == NEWLINE:
            pos += 1
        if pos >= n or tokens[pos].kind != RPAREN:
            return None, pos, "unstash call is missing closing ')'"
        pos += 1
    if not valid_stash_name(dec.value):
        return None, pos, f"invalid stash name '{dec.value}'"
    return dec.value, pos, None


def validate_job_stashes(pipeline) -> list[Finding]:
    """Enforce single-job stash uniqueness and unstash-after-stash ordering."""
    if pipeline is None or pipeline.blocked:
        return []
    findings: list[Finding] = []
    seen_stashes: set[str] = set()
    for stage in pipeline.stages:
        if stage.blocked:
            continue
        stage_stashes: set[str] = set()
        for step in stage.steps:
            if step.kind == "stash":
                if step.text in seen_stashes or step.text in stage_stashes:
                    findings.append(
                        Finding(
                            code=PB_LIB_CALL,
                            severity="blocker",
                            construct="stash step",
                            message=f"stash name '{step.text}' is already used in this job.",
                            line=step.span.line,
                            col=step.span.col,
                            suggestion="Use a unique stash name per job.",
                            source_path=step.source_path,
                        )
                    )
                    stage.blocked = True
                    stage.steps.clear()
                    break
                stage_stashes.add(step.text)
            elif step.kind == "unstash":
                if step.text not in seen_stashes and step.text not in stage_stashes:
                    findings.append(
                        Finding(
                            code=PB_LIB_CALL,
                            severity="blocker",
                            construct="unstash step",
                            message=f"unstash '{step.text}' has no earlier stash of that name in this job.",
                            line=step.span.line,
                            col=step.span.col,
                            suggestion="Ensure an unblocked earlier step in this job stashes that name.",
                            source_path=step.source_path,
                        )
                    )
                    stage.blocked = True
                    stage.steps.clear()
                    break
        if not stage.blocked:
            seen_stashes.update(stage_stashes)
    return findings


STASH_HELPER_SOURCE = '''\
"""Pipebridge bounded single-job stash helper."""

import os
import re
import shutil
import sys
from pathlib import Path

STASH_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
LITERAL_SEG_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _valid_glob(pattern: str) -> bool:
    if not pattern or "\\\\" in pattern or pattern.startswith("/") or pattern.endswith("/"):
        return False
    for seg in pattern.split("/"):
        if seg in ("", ".", ".."):
            return False
        if seg in ("*", "**"):
            continue
        if LITERAL_SEG_RE.fullmatch(seg) is None:
            return False
    return True


def _match_segments(pat_segs: list[str], path_segs: list[str]) -> bool:
    if not pat_segs:
        return not path_segs
    if pat_segs[0] == "**":
        return _match_segments(pat_segs[1:], path_segs) or (
            bool(path_segs) and _match_segments(pat_segs, path_segs[1:])
        )
    if not path_segs:
        return False
    if pat_segs[0] == "*" or pat_segs[0] == path_segs[0]:
        return _match_segments(pat_segs[1:], path_segs[1:])
    return False


def _matches(pattern: str, rel_posix: str) -> bool:
    return _match_segments(pattern.split("/"), rel_posix.split("/"))


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print("pipebridge-stash: usage: pipebridge_stash.py <name> <includes> [excludes]", file=sys.stderr)
        return 2
    name, includes = argv[0], argv[1]
    excludes = argv[2] if len(argv) == 3 else None
    if STASH_NAME_RE.fullmatch(name) is None:
        print(f"pipebridge-stash: invalid stash name: {name}", file=sys.stderr)
        return 2
    if not _valid_glob(includes):
        print(f"pipebridge-stash: invalid includes glob: {includes}", file=sys.stderr)
        return 2
    if excludes is not None and not _valid_glob(excludes):
        print(f"pipebridge-stash: invalid excludes glob: {excludes}", file=sys.stderr)
        return 2

    ws_env = os.environ.get("GITHUB_WORKSPACE", "")
    rt_env = os.environ.get("RUNNER_TEMP", "")
    if not ws_env or not rt_env:
        print("pipebridge-stash: GITHUB_WORKSPACE and RUNNER_TEMP must be set", file=sys.stderr)
        return 2

    workspace = Path(ws_env).resolve()
    stash_root = Path(rt_env).resolve() / "pipebridge-stash"
    dest = stash_root / name
    try:
        dest.resolve().relative_to(stash_root)
    except ValueError:
        print(f"pipebridge-stash: stash destination escapes root: {dest}", file=sys.stderr)
        return 2
    if dest.exists() or dest.is_symlink():
        print(f"pipebridge-stash: stash destination already exists: {name}", file=sys.stderr)
        return 2

    matched: list[tuple[Path, Path]] = []
    for dirpath, dirnames, filenames in os.walk(workspace, followlinks=False):
        dirnames.sort()
        filenames.sort()
        cur_dir = Path(dirpath)
        for dname in dirnames:
            cand = cur_dir / dname
            if cand.is_symlink():
                rel = cand.relative_to(workspace).as_posix()
                if _matches(includes, rel) and (excludes is None or not _matches(excludes, rel)):
                    print(f"pipebridge-stash: symlink matched: {rel}", file=sys.stderr)
                    return 2
        for fname in filenames:
            cand = cur_dir / fname
            rel_path = cand.relative_to(workspace)
            rel = rel_path.as_posix()
            if not _matches(includes, rel):
                continue
            if excludes is not None and _matches(excludes, rel):
                continue
            if cand.is_symlink():
                print(f"pipebridge-stash: symlink matched: {rel}", file=sys.stderr)
                return 2
            try:
                cand.resolve().relative_to(workspace)
            except ValueError:
                print(f"pipebridge-stash: path escapes workspace: {rel}", file=sys.stderr)
                return 2
            if not cand.is_file():
                continue
            matched.append((cand, rel_path))

    if not matched:
        print("pipebridge-stash: no files matched", file=sys.stderr)
        return 1

    created = False
    try:
        dest.mkdir(parents=True, exist_ok=False)
        created = True
        for src_file, rel_path in matched:
            target = dest / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, target)
    except OSError as exc:
        if created:
            shutil.rmtree(dest, ignore_errors=True)
        print(f"pipebridge-stash: failed copying files: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''


UNSTASH_HELPER_SOURCE = '''\
"""Pipebridge bounded single-job unstash helper."""

import os
import re
import shutil
import sys
from pathlib import Path

STASH_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def _validate_dest_path(workspace: Path, rel: Path) -> Path | None:
    if rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
        return None
    cur = workspace
    for part in rel.parts[:-1]:
        cur = cur / part
        if cur.is_symlink():
            return None
        try:
            cur.resolve().relative_to(workspace)
        except ValueError:
            return None
    target = workspace / rel
    if target.is_symlink():
        return None
    try:
        (target.parent.resolve() / target.name).relative_to(workspace)
    except ValueError:
        return None
    return target


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("pipebridge-unstash: usage: pipebridge_unstash.py <name>", file=sys.stderr)
        return 2
    name = argv[0]
    if STASH_NAME_RE.fullmatch(name) is None:
        print(f"pipebridge-unstash: invalid stash name: {name}", file=sys.stderr)
        return 2

    ws_env = os.environ.get("GITHUB_WORKSPACE", "")
    rt_env = os.environ.get("RUNNER_TEMP", "")
    if not ws_env or not rt_env:
        print("pipebridge-unstash: GITHUB_WORKSPACE and RUNNER_TEMP must be set", file=sys.stderr)
        return 2

    workspace = Path(ws_env).resolve()
    stash_root = Path(rt_env).resolve() / "pipebridge-stash"
    src = stash_root / name
    if src.is_symlink():
        print(f"pipebridge-unstash: stash source is a symlink: {name}", file=sys.stderr)
        return 2
    if not src.exists():
        print("pipebridge-unstash: stash not found", file=sys.stderr)
        return 1
    src_resolved = src.resolve()
    try:
        src_resolved.relative_to(stash_root)
    except ValueError:
        print(f"pipebridge-unstash: stash source escapes root: {name}", file=sys.stderr)
        return 2
    if not src_resolved.is_dir():
        print("pipebridge-unstash: stash not found", file=sys.stderr)
        return 1

    # Validate ALL source files and destination paths/parents before copying anything.
    copies: list[tuple[Path, Path]] = []
    for dirpath, dirnames, filenames in os.walk(src_resolved, followlinks=False):
        dirnames.sort()
        filenames.sort()
        cur_dir = Path(dirpath)
        for dname in dirnames:
            if (cur_dir / dname).is_symlink():
                print(f"pipebridge-unstash: symlink in stash: {dname}", file=sys.stderr)
                return 2
        for fname in filenames:
            src_file = cur_dir / fname
            if src_file.is_symlink():
                print(f"pipebridge-unstash: symlink in stash: {fname}", file=sys.stderr)
                return 2
            try:
                src_file.resolve().relative_to(src_resolved)
            except ValueError:
                print(f"pipebridge-unstash: stash file escapes root: {fname}", file=sys.stderr)
                return 2
            rel = src_file.relative_to(src_resolved)
            dst_file = _validate_dest_path(workspace, rel)
            if dst_file is None:
                print(f"pipebridge-unstash: destination path escapes workspace: {rel}", file=sys.stderr)
                return 2
            copies.append((src_file, dst_file))

    for src_file, dst_file in copies:
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''
