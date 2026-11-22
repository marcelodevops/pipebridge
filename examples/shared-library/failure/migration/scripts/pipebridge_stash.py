"""Pipebridge bounded single-job stash helper."""

import os
import re
import shutil
import sys
from pathlib import Path

STASH_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
LITERAL_SEG_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _valid_glob(pattern: str) -> bool:
    if not pattern or "\\" in pattern or pattern.startswith("/") or pattern.endswith("/"):
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


def _can_descendant_match(pat_segs: list[str], dir_segs: list[str]) -> bool:
    if not dir_segs:
        return bool(pat_segs)
    if not pat_segs:
        return False
    if pat_segs[0] == "**":
        return _can_descendant_match(pat_segs[1:], dir_segs) or _can_descendant_match(
            pat_segs, dir_segs[1:]
        )
    if pat_segs[0] == "*" or pat_segs[0] == dir_segs[0]:
        return _can_descendant_match(pat_segs[1:], dir_segs[1:])
    return False


def _all_descendants_match(pat_segs: list[str], dir_segs: list[str]) -> bool:
    if pat_segs == ["**"]:
        return True
    if not pat_segs or not dir_segs:
        return False
    if pat_segs[0] == "**":
        return _all_descendants_match(pat_segs[1:], dir_segs) or _all_descendants_match(
            pat_segs, dir_segs[1:]
        )
    if pat_segs[0] == "*" or pat_segs[0] == dir_segs[0]:
        return _all_descendants_match(pat_segs[1:], dir_segs[1:])
    return False


def _symlink_dir_could_match(includes: str, excludes: str | None, rel_posix: str) -> bool:
    dir_segs = rel_posix.split("/")
    inc_segs = includes.split("/")
    if not (_matches(includes, rel_posix) or _can_descendant_match(inc_segs, dir_segs)):
        return False
    if excludes is not None:
        exc_segs = excludes.split("/")
        if _all_descendants_match(exc_segs, dir_segs):
            return False
    return True


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
                if _symlink_dir_could_match(includes, excludes, rel):
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
