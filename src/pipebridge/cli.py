"""Command-line interface: analyze, convert, --version.

Exit codes:
- 0: analysis or conversion completed without migration blockers
- 1: malformed input, I/O failure, usage error, or internal error
- 2: analysis or conversion completed with migration blockers
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from . import __version__
from .analysis import analyze_source
from .errors import PipebridgeError
from .findings import Finding, PB_SHELLCHECK
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
    return parser


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


def _cmd_analyze(args) -> int:
    path, text = _read_source(args.jenkinsfile)
    analysis = analyze_source(text)
    report = build_report(analysis, source_path=str(path), validation=None)
    if args.format == "json":
        sys.stdout.write(render_json_report(report))
    else:
        sys.stdout.write(render_markdown_report(report))
    return int(report["exit_code"])


# ---- convert ------------------------------------------------------------

_OUTPUT_FILES = ("workflow.yml", "migration-report.md", "migration-report.json")


def _cmd_convert(args) -> int:
    path, text = _read_source(args.jenkinsfile)
    analysis = analyze_source(text)
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
        disabled=bool(analysis.has_blockers),
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
        ]
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
    return int(report["exit_code"])


def _write_all(items: list[tuple[Path, str]]) -> None:
    """Write files via temp+rename; on failure, remove partial artifacts."""
    written: list[Path] = []
    try:
        for target, content in items:
            temp = target.with_name(f".{target.name}.tmp")
            temp.write_text(content, encoding="utf-8")
            os.replace(temp, target)
            written.append(target)
    except OSError:
        for target in written:
            target.unlink(missing_ok=True)
        raise PipebridgeError(f"failed writing generated files: {items[-1][0]}")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
