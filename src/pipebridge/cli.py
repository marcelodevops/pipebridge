"""Command-line interface: analyze, convert, --version.

Exit codes:
- 0: analysis or conversion completed without migration blockers
- 1: malformed input, I/O failure, usage error, or internal error
- 2: analysis or conversion completed with migration blockers
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import uuid
from pathlib import Path

from . import __version__
from .analysis import analyze_source
from .credentials import load_credential_map
from .errors import PipebridgeError
from .findings import Finding, PB_SHELLCHECK
from .librarymap import load_library_map
from .reporting import build_report, render_json_report, render_markdown_report
from .validation import validate_generated_workflow
from .workflow import generate_workflow


class _UsageError(PipebridgeError):
    pass


class _Parser(argparse.ArgumentParser):
    # Usage errors are "malformed input" for pipebridge: exit 1, not argparse's 2.
    def error(self, message):  # noqa: D401
        raise _UsageError(message)


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="pipebridge",
        description=(
            "Migrate declarative Jenkins pipelines to GitHub Actions workflows "
            "with actionable migration reports."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"pipebridge {__version__}"
    )
    sub = parser.add_subparsers(dest="command")

    p_analyze = sub.add_parser(
        "analyze", help="analyze a Jenkinsfile and print findings; writes nothing"
    )
    p_analyze.add_argument("jenkinsfile", help="path to the Jenkinsfile")
    p_analyze.add_argument(
        "--format", choices=["text", "json"], default="text", help="output format"
    )
    _add_credential_args(p_analyze)
    _add_library_arg(p_analyze)

    p_convert = sub.add_parser(
        "convert", help="generate workflow.yml and migration reports"
    )
    p_convert.add_argument("jenkinsfile", help="path to the Jenkinsfile")
    p_convert.add_argument(
        "--output", required=True, help="directory for generated artifacts"
    )
    p_convert.add_argument(
        "--force",
        action="store_true",
        help="replace existing generated files (default: never overwrite)",
    )
    _add_credential_args(p_convert)
    _add_library_arg(p_convert)
    return parser


def _add_credential_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--credential-map",
        help=(
            "JSON file mapping Jenkins credential IDs to GitHub secret names. "
            "Names only; pipebridge never reads secret values."
        ),
    )
    parser.add_argument(
        "--secrets-ready",
        action="store_true",
        help=(
            "Acknowledge that every secret named by the credential map exists "
            "in the target repository. Does not read or verify values."
        ),
    )


def _add_library_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--library-map",
        help=(
            "JSON file mapping Jenkins shared-library names to local "
            "directories. Paths only; pipebridge never fetches repositories "
            "or executes Groovy."
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        if not getattr(args, "command", None):
            parser.error("a command is required: 'analyze' or 'convert'")
        if args.command == "analyze":
            return _cmd_analyze(args)
        return _cmd_convert(args)
    except SystemExit as exc:  # --version / -h exit via SystemExit(0)
        return int(exc.code or 0)
    except PipebridgeError as exc:
        print(f"pipebridge: error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # internal error: report honestly, exit 1
        print(f"pipebridge: internal error: {exc!r}", file=sys.stderr)
        return 1


# ---- shared helpers -----------------------------------------------------


def _read_source(path_text: str) -> tuple[Path, str]:
    path = Path(path_text)
    if not path.exists():
        raise PipebridgeError(f"input file not found: {path}")
    if not path.is_file():
        raise PipebridgeError(f"input path is not a file: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PipebridgeError(f"cannot read {path}: {exc}") from exc
    return path, text


# ---- analyze ------------------------------------------------------------


def _load_credential_map(args):
    path_text = getattr(args, "credential_map", None)
    if not path_text:
        return None
    return load_credential_map(Path(path_text))


def _load_library_map(args):
    path_text = getattr(args, "library_map", None)
    if not path_text:
        return None
    return load_library_map(Path(path_text))


def _cmd_analyze(args) -> int:
    credential_map = _load_credential_map(args)
    library_map = _load_library_map(args)
    path, text = _read_source(args.jenkinsfile)
    analysis = analyze_source(
        text,
        credential_map=credential_map,
        secrets_ready=bool(args.secrets_ready),
        library_map=library_map,
        source_path=str(path),
    )
    report = build_report(analysis, source_path=str(path), validation=None)
    if args.format == "json":
        sys.stdout.write(render_json_report(report))
    else:
        sys.stdout.write(render_markdown_report(report))
    return int(report["exit_code"])


# ---- convert ------------------------------------------------------------

_OUTPUT_FILES = ("workflow.yml", "migration-report.md", "migration-report.json")


def _cmd_convert(args) -> int:
    # Structural map errors must fail before any artifact is written.
    credential_map = _load_credential_map(args)
    library_map = _load_library_map(args)
    path, text = _read_source(args.jenkinsfile)
    analysis = analyze_source(
        text,
        credential_map=credential_map,
        secrets_ready=bool(args.secrets_ready),
        library_map=library_map,
        source_path=str(path),
    )
    workflow_text = generate_workflow(analysis, source_name=path.name)

    output_dir = Path(args.output)
    if output_dir.exists() and not output_dir.is_dir():
        raise PipebridgeError(f"output path exists and is not a directory: {output_dir}")

    targets = [output_dir / name for name in _OUTPUT_FILES]
    existing = [t for t in targets if t.exists()]
    if existing and not args.force:
        listing = ", ".join(str(t) for t in existing)
        raise PipebridgeError(
            f"refusing to overwrite existing file(s): {listing}. Use --force to replace them."
        )

    # Validate the fully rendered workflow BEFORE creating anything, so a
    # failed conversion never leaves a partial set of artifacts. The
    # deliberate `if: false` disabled state is disclosed as the single
    # suppressed lint rule.
    validation = validate_generated_workflow(
        workflow_text,
        targets[0],
        disabled=bool(analysis.conversion_blocked),
    )

    # shellcheck notes are about the user's faithfully-migrated script:
    # surface them as warnings instead of failing the conversion.
    notes = (validation.get("actionlint") or {}).get("shellcheck_notes") or []
    for note in notes:
        analysis.findings.append(
            Finding(
                code=PB_SHELLCHECK,
                severity="warning",
                construct="generated workflow script",
                message=note,
                line=0,
                col=0,
                suggestion=(
                    "The script text was preserved verbatim from the source; fix the "
                    "quoting in the Jenkinsfile (or the generated workflow) deliberately."
                ),
            )
        )

    report = build_report(analysis, source_path=str(path), validation=validation)
    markdown_text = render_markdown_report(report)
    json_text = render_json_report(report)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_all(
        [
            (targets[0], workflow_text),
            (targets[1], markdown_text),
            (targets[2], json_text),
        ],
        protected=path,
    )

    summary = report["summary"]
    print(
        f"Wrote {targets[0]}, {targets[1]}, {targets[2]}"
    )
    print(
        f"Result: {summary['blockers']} blocker(s), {summary['warnings']} warning(s), "
        f"{summary['info']} info finding(s); exit code {report['exit_code']}"
    )
    if summary["blockers"]:
        print(
            "The generated job is disabled with `if: false`; resolve every "
            "blocker in the report before enabling it."
        )
    elif int(report["exit_code"]) != 0:
        print(
            "The generated job is disabled with `if: false` because "
            "shared-library script emission is deferred."
        )
    return int(report["exit_code"])


def _write_all(items: list[tuple[Path, str]], protected: Path | None = None) -> None:
    """Stage every artifact, then commit replacements one rename at a time.

    Guarantees (deliberately honest — this is NOT a crash-atomic
    multi-file transaction; a process kill between renames can leave a
    partial set on disk):

    - Nothing is written until ALL artifacts are staged and the previous
      contents backed up; staging/backup failures leave every target
      untouched. Temporary and backup paths are registered BEFORE the
      write/copy that creates them, so a failure that leaves partially
      written bytes on disk is still cleaned up.
    - A handled (OSError) failure during the commit renames rolls back:
      previously existing files are restored byte-for-byte from backups,
      newly introduced outputs are removed, and all temporary files are
      cleaned. Unrelated files are never touched.
    - Rollback attempts EVERY committed target even if one restoration
      fails. A restoration that fails is reported as an INCOMPLETE
      rollback: the backup is preserved (it holds the only surviving copy
      of the original bytes) and the error names each affected target and
      the exact backup path for manual recovery. A rollback with no such
      failures is reported as complete. Backups are only ever removed
      after the replacement was committed (success path) or restored
      (consumed by the rollback rename) — or when the target itself still
      holds the original bytes (never committed), making the backup a
      redundant copy.
    - Temporary paths are unique per run (uuid-suffixed) so parallel or
      repeated runs cannot collide.
    - Any target that resolves to ``protected`` (the input Jenkinsfile) is
      rejected before anything is written.
    """
    protected_resolved = protected.resolve() if protected is not None else None
    for target, _content in items:
        if protected_resolved is not None and target.resolve() == protected_resolved:
            raise PipebridgeError(
                f"refusing to overwrite the input Jenkinsfile: {target}"
            )

    staged: list[tuple[Path, Path]] = []  # (temp, target)
    backups: list[tuple[Path, Path]] = []  # (backup, target), existing targets only
    committed: list[tuple[Path, Path | None]] = []  # (target, backup-or-None)
    # Restorations that failed: (target, backup). The backup is the only
    # surviving copy of the original bytes and must never be deleted.
    unrestored: list[tuple[Path, Path]] = []
    try:
        # Phase 1: stage every artifact next to its target (same directory
        # => same filesystem => the later rename is atomic). The temp path
        # is registered BEFORE writing so a partial write that raises is
        # still removed by cleanup.
        for target, content in items:
            temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            staged.append((temp, target))
            temp.write_text(content, encoding="utf-8")

        # Phase 2: back up every pre-existing target byte-for-byte. The
        # backup path is registered BEFORE copying so a partial copy that
        # raises is still removed by cleanup.
        for _temp, target in staged:
            if target.exists():
                backup = target.with_name(f".{target.name}.{uuid.uuid4().hex}.bak")
                backups.append((backup, target))
                shutil.copyfile(target, backup)

        # Phase 3: commit. On a handled failure, undo everything that was
        # committed so far.
        try:
            for temp, target in staged:
                os.replace(temp, target)
                committed.append((target, _backup_for(backups, target)))
        except OSError as exc:
            unrestored, unremoved = _rollback(committed)
            parts = [f"failed writing generated files: {exc}"]
            if not unrestored and not unremoved:
                parts.append("rolled back completely")
            else:
                parts.append(
                    "ROLLBACK INCOMPLETE: rollback could not be completed "
                    "for every target"
                )
                if unrestored:
                    recovery = "; ".join(
                        f"{target} -> recover previous contents from {backup}"
                        for target, backup in unrestored
                    )
                    parts.append(
                        "previous contents were NOT restored and are preserved "
                        f"in recovery backups: {recovery}"
                    )
                if unremoved:
                    parts.append(
                        "newly written files could NOT be removed: "
                        + ", ".join(str(t) for t in unremoved)
                    )
            raise PipebridgeError("; ".join(parts)) from exc
    except PipebridgeError:
        _cleanup(staged, backups, preserve_backups={b for _, b in unrestored})
        raise
    except OSError as exc:
        _cleanup(staged, backups)
        raise PipebridgeError(f"failed writing generated files: {exc}") from exc
    # Success: every replacement was committed; consume the backups (they
    # are no longer needed).
    for backup, _target in backups:
        backup.unlink(missing_ok=True)


def _backup_for(backups: list[tuple[Path, Path]], target: Path) -> Path | None:
    for backup, backed_up in backups:
        if backed_up == target:
            return backup
    return None


def _rollback(
    committed: list[tuple[Path, Path | None]],
) -> tuple[list[tuple[Path, Path]], list[Path]]:
    """Undo committed replacements, newest first.

    Every committed target is attempted even if an earlier restoration
    fails. Returns (unrestored, unremoved): restorations that failed —
    their backups still hold the only surviving copy of the original
    bytes — and newly-introduced targets that could not be removed.
    """
    unrestored: list[tuple[Path, Path]] = []
    unremoved: list[Path] = []
    for target, backup in reversed(committed):
        try:
            if backup is not None:
                os.replace(backup, target)  # byte-for-byte restore
            else:
                target.unlink(missing_ok=True)  # newly introduced: remove
        except OSError:
            if backup is not None:
                unrestored.append((target, backup))
            else:
                unremoved.append(target)
    return unrestored, unremoved


def _cleanup(
    staged: list[tuple[Path, Path]],
    backups: list[tuple[Path, Path]],
    preserve_backups: frozenset[Path] | set[Path] = frozenset(),
) -> None:
    """Best-effort removal of temporary files left behind.

    Backups in ``preserve_backups`` (restorations that failed) are NEVER
    removed: they hold the only surviving copy of the user's original
    data.
    """
    for temp, _target in staged:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
    for backup, _target in backups:
        if backup in preserve_backups:
            continue
        try:
            backup.unlink(missing_ok=True)
        except OSError:
            pass


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
