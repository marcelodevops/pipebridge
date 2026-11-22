"""Pipebridge bounded single-job unstash helper."""

import os
import re
import shutil
import stat
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
        if os.path.lexists(cur) and not stat.S_ISDIR(cur.lstat().st_mode):
            return None
        try:
            cur.resolve().relative_to(workspace)
        except ValueError:
            return None
    target = workspace / rel
    if target.is_symlink():
        return None
    if os.path.lexists(target) and not stat.S_ISREG(target.lstat().st_mode):
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
    copies: list[tuple[Path, Path, Path]] = []
    for dirpath, dirnames, filenames in os.walk(src_resolved, followlinks=False):
        dirnames.sort()
        filenames.sort()
        cur_dir = Path(dirpath)
        for dname in dirnames:
            dpath = cur_dir / dname
            if dpath.is_symlink():
                print(f"pipebridge-unstash: symlink in stash: {dname}", file=sys.stderr)
                return 2
        for fname in filenames:
            src_file = cur_dir / fname
            if src_file.is_symlink():
                print(f"pipebridge-unstash: symlink in stash: {fname}", file=sys.stderr)
                return 2
            try:
                src_st = src_file.lstat()
            except OSError as exc:
                print(f"pipebridge-unstash: cannot stat stash entry {fname}: {exc}", file=sys.stderr)
                return 2
            if not stat.S_ISREG(src_st.st_mode):
                print(f"pipebridge-unstash: unsupported non-regular file in stash: {fname}", file=sys.stderr)
                return 2
            try:
                src_file.resolve().relative_to(src_resolved)
            except ValueError:
                print(f"pipebridge-unstash: stash file escapes root: {fname}", file=sys.stderr)
                return 2
            rel = src_file.relative_to(src_resolved)
            dst_file = _validate_dest_path(workspace, rel)
            if dst_file is None:
                print(f"pipebridge-unstash: invalid destination path: {rel}", file=sys.stderr)
                return 2
            copies.append((src_file, dst_file, rel))

    for src_file, dst_file, rel in copies:
        try:
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
        except OSError as exc:
            print(f"pipebridge-unstash: failed restoring {rel}: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
