"""Migration reports in JSON and Markdown."""

from __future__ import annotations

import datetime
import json

from . import __version__
from .model import STATUS_RESOLVED, CredentialInventory, LibraryInventory

_TRUNCATE = 72


def build_report(analysis, source_path: str, validation: dict | None) -> dict:
    """Assemble the canonical report dict shared by JSON and Markdown output."""
    findings = analysis.findings
    blockers = [f for f in findings if f.severity == "blocker"]
    warnings = [f for f in findings if f.severity == "warning"]
    infos = [f for f in findings if f.severity == "info"]

    translated_stages: list[dict] = []
    translated_steps = 0
    pipeline = analysis.pipeline
    if pipeline is not None:
        for stage in pipeline.stages:
            entry = {
                "stage": stage.name,
                "source_line": stage.span.line,
                "blocked": stage.blocked,
                "steps": [],
            }
            if not stage.blocked:
                for step in stage.steps:
                    step_entry: dict = {
                        "kind": step.kind,
                        "source_line": step.span.line,
                        "detail": step.text,
                    }
                    if getattr(step, "script_path", None) is not None:
                        step_entry["script_path"] = step.script_path
                    if getattr(step, "source_path", None) is not None:
                        step_entry["source_path"] = step.source_path
                    if getattr(step, "args", ()):
                        step_entry["args"] = list(step.args)
                    entry["steps"].append(step_entry)
                    translated_steps += 1
            translated_stages.append(entry)

    if validation is None:
        validation = {
            "yaml_parse": {
                "ok": None,
                "error": None,
                "note": "not run (no workflow generated)",
            },
            "actionlint": {
                "available": False,
                "ok": None,
                "note": "not run (no workflow generated)",
            },
            "runtime": {
                "performed": False,
                "note": "not performed (no workflow generated)",
            },
        }

    library_deferred = bool(getattr(analysis, "library_emission_deferred", False))
    conversion_blocked = bool(blockers) or library_deferred

    return {
        "tool": {"name": "pipebridge", "version": __version__},
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "source": {"path": source_path, "sha256": analysis.source_sha256},
        "exit_code": 2 if conversion_blocked else 0,
        "summary": {
            "blockers": len(blockers),
            "warnings": len(warnings),
            "info": len(infos),
            "translated_stages": len(translated_stages),
            "translated_steps": translated_steps,
        },
        "findings": [_finding_dict(f) for f in findings],
        "blockers": [f.code for f in blockers],
        "assumptions": [f.code for f in infos],
        "translated": translated_stages,
        "credentials": _credentials_section(analysis),
        "libraries": _libraries_section(analysis),
        "validation": validation,
    }


def _libraries_section(analysis) -> dict:
    inventory = getattr(analysis, "library_inventory", None) or LibraryInventory()
    loaded = [
        {
            "name": lib.name,
            "path": lib.path,
            "revision": lib.revision,
            "discovered_vars": list(lib.discovered_vars),
            "vars": list(lib.vars),
        }
        for lib in inventory.libraries
    ]
    calls = [
        {
            "name": call.name,
            "status": call.status,
            "source_path": call.source_path,
            "line": call.line,
            "col": call.col,
            "chain": list(call.chain),
        }
        for call in inventory.calls
    ]
    return {
        "map_supplied": bool(inventory.map_supplied),
        "conversion_deferred": bool(
            getattr(analysis, "library_emission_deferred", False)
        ),
        "loaded": loaded,
        "calls": calls,
    }


def _credentials_section(analysis) -> dict:
    inventory = getattr(analysis, "credential_inventory", None) or CredentialInventory()
    bindings = []
    grouped: dict[str, dict[str, list[str]]] = {}
    for entry in inventory.entries:
        bindings.append(
            {
                "binding_id": entry.binding_id,
                "binding_type": entry.binding_type,
                "credential_id": entry.credential_id,
                "variable": entry.variable,
                "secret_name": entry.secret_name,
                "stage": entry.stage_name,
                "source_line": entry.span.line,
                "source_col": entry.span.col,
                "status": entry.status,
                "reason": entry.reason,
            }
        )
        if entry.status == STATUS_RESOLVED and entry.secret_name:
            bucket = grouped.setdefault(
                entry.secret_name, {"credential_ids": [], "variables": []}
            )
            if entry.credential_id and entry.credential_id not in bucket["credential_ids"]:
                bucket["credential_ids"].append(entry.credential_id)
            if entry.variable and entry.variable not in bucket["variables"]:
                bucket["variables"].append(entry.variable)
    required = sorted(grouped)
    return {
        "map_supplied": bool(getattr(analysis, "credential_map_supplied", False)),
        "setup_acknowledged": bool(getattr(analysis, "secrets_ready", False)),
        "bindings": bindings,
        "required_secrets": required,
        "checklist": [
            {
                "secret_name": name,
                "credential_ids": grouped[name]["credential_ids"],
                "variables": grouped[name]["variables"],
            }
            for name in required
        ],
    }


def _markdown_credentials(credentials: dict) -> list[str]:
    bindings = credentials.get("bindings") or []
    if not bindings:
        return []
    lines = [
        "## Required GitHub Actions secrets",
        "",
        "pipebridge never reads, prints, embeds, or invents secret values. It only "
        "knows the secret names supplied in the mapping file.",
        "",
        "| Credential ID | Bound variable | GitHub secret | Status | Reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in bindings:
        lines.append(
            "| {cid} | {var} | {secret} | {status} | {reason} |".format(
                cid=_md_cell(entry.get("credential_id")),
                var=_md_cell(entry.get("variable")),
                secret=_md_cell(entry.get("secret_name")),
                status=entry.get("status") or "—",
                reason=_md_cell(entry.get("reason"), quote=False),
            )
        )
    lines.append("")
    unresolved = [entry for entry in bindings if entry.get("status") != STATUS_RESOLVED]
    if unresolved:
        lines.append(
            "An explicit credential-ID to secret-name mapping is required for every "
            "unresolved row. pipebridge does not guess a secret name or emit a "
            "create command for those rows."
        )
        lines.append("")
    required = credentials.get("required_secrets") or []
    if required:
        lines.extend(
            [
                "### Create each secret",
                "",
                "GitHub UI:",
                "",
                "1. Open the target repository on GitHub.",
                "2. Go to **Settings → Secrets and variables → Actions**.",
                "3. Select **New repository secret**.",
                "4. Enter the name **exactly** as shown above.",
                "5. Enter the value yourself. pipebridge never sees, prints, or stores it.",
                "6. Select **Add secret**.",
                "",
                "`gh` CLI, from a clone of the target repository with `gh auth login` already completed:",
                "",
                "```sh",
            ]
        )
        for name in required:
            lines.append(f"gh secret set {name}")
        lines.extend(
            [
                "# gh prompts for the value; do not pass the value on the command line.",
                "```",
                "",
                "Outside the clone, add `--repo <owner>/<repo>` yourself. pipebridge does not "
                "guess or invent the repository.",
                "",
                "After every secret above exists, re-run the same conversion with the same "
                "`--credential-map` plus `--secrets-ready`. That flag is an acknowledgement, "
                "not a verification: pipebridge still does not read or test the secret.",
                "",
            ]
        )
    return lines


def _md_cell(value: str | None, quote: bool = True) -> str:
    if not value:
        return "—"
    text = (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("`", "\\`")
        .replace("\n", " ")
    )
    return f"`{text}`" if quote else text


def _finding_dict(f) -> dict:
    item = {
        "code": f.code,
        "severity": f.severity,
        "construct": f.construct,
        "message": f.message,
        "line": f.line,
        "col": f.col,
        "suggestion": f.suggestion,
    }
    if getattr(f, "source_path", None) is not None:
        item["source_path"] = f.source_path
    if getattr(f, "call_chain", ()):
        item["call_chain"] = list(f.call_chain)
    return item


def render_json_report(report: dict) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"


def render_markdown_report(report: dict) -> str:
    lines: list[str] = []
    summary = report["summary"]
    src = report["source"]
    lines.append("# Migration report")
    lines.append("")
    lines.append(f"- **Source:** `{src['path']}` (sha256 `{src['sha256']}`)")
    lines.append(
        f"- **Tool:** {report['tool']['name']} {report['tool']['version']}"
    )
    lines.append(f"- **Generated:** {report['generated_at']}")
    if summary["blockers"]:
        lines.append(
            f"- **Result:** converted **with {summary['blockers']} blocker(s)** — "
            "the generated job is DISABLED (`if: false`)"
        )
    elif report["exit_code"] != 0:
        lines.append(
            "- **Result:** converted **with deferred library emission** — "
            "the generated job is DISABLED (`if: false`)"
        )
    else:
        lines.append("- **Result:** converted without blockers (review assumptions below)")
    lines.append(f"- **Exit code:** {report['exit_code']}")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Severity | Count |")
    lines.append("| --- | --- |")
    lines.append(f"| blocker | {summary['blockers']} |")
    lines.append(f"| warning | {summary['warnings']} |")
    lines.append(f"| info | {summary['info']} |")
    lines.append(f"| translated stages | {summary['translated_stages']} |")
    lines.append(f"| translated steps | {summary['translated_steps']} |")
    lines.append("")

    lines.append("## Translated items")
    lines.append("")
    lines.append("| Stage | Step kind | Source line | Detail |")
    lines.append("| --- | --- | --- | --- |")
    had_stage = False
    for stage in report["translated"]:
        had_stage = True
        if stage["blocked"]:
            lines.append(
                f"| {stage['stage']} | — | {stage['source_line']} | "
                "**not migrated** (contains blockers; placeholder step fails loudly) |"
            )
            continue
        for i, step in enumerate(stage["steps"], start=1):
            lines.append(
                f"| {stage['stage']} | {step['kind']} | {step['source_line']} | "
                f"`{_short(step['detail'])}` |"
            )
        if not stage["steps"]:
            lines.append(f"| {stage['stage']} | — | {stage['source_line']} | (no steps) |")
    if not had_stage:
        lines.append("| — | — | — | No declarative pipeline was parsed. |")
    lines.append("")

    cred_lines = _markdown_credentials(report.get("credentials") or {})
    if cred_lines:
        lines.extend(cred_lines)

    lib_lines = _markdown_libraries(report.get("libraries") or {})
    if lib_lines:
        lines.extend(lib_lines)

    findings = report["findings"]
    for title, severity in (("Blockers", "blocker"), ("Warnings", "warning"), ("Assumptions", "info")):
        lines.append(f"## {title}")
        lines.append("")
        group = [f for f in findings if f["severity"] == severity]
        if not group:
            lines.append("None.")
            lines.append("")
            continue
        for f in group:
            lines.append(
                f"### {f['code']} — {f['construct']} {_finding_location(f)}"
            )
            lines.append("")
            lines.append(f"- {f['message']}")
            if f.get("call_chain"):
                chain_text = " -> ".join(f["call_chain"])
                lines.append(f"- **Call chain:** `{chain_text}`")
            lines.append(f"- **Next action:** {f['suggestion']}")
            lines.append("")

    lines.append("## Validation")
    lines.append("")
    lines.append("| Check | Result |")
    lines.append("| --- | --- |")
    v = report["validation"]
    yaml_v = v.get("yaml_parse") or {}
    lint_v = v.get("actionlint") or {}
    runtime_v = v.get("runtime") or {}
    lines.append(f"| YAML parse | {_fmt_yaml(yaml_v)} |")
    lines.append(f"| actionlint | {_fmt_actionlint(lint_v)} |")
    lines.append(f"| Runtime execution | {_fmt_runtime(runtime_v)} |")
    lines.append("")
    lines.append(
        "> pipebridge reports what it verified and nothing more: YAML parsing and "
        "linting are static checks; runtime behavior was **not** validated."
    )
    lines.append("")
    return "\n".join(lines)


def _markdown_libraries(libraries: dict) -> list[str]:
    loaded = libraries.get("loaded") or []
    calls = libraries.get("calls") or []
    if not loaded and not calls:
        return []
    lines = [
        "## Libraries",
        "",
        "Local library directories were used for static analysis only; pipebridge "
        "did not fetch repositories or execute Groovy.",
        "",
    ]
    if libraries.get("conversion_deferred"):
        lines.append(
            "Shared-library script emission is deferred; conversion remains "
            "blocked (exit 2, `if: false`) even when static resolution succeeds."
        )
        lines.append("")
    if loaded:
        lines.extend(
            [
                "| Library | Local path | Revision (unverified) | Discovered vars | Reached vars |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for lib in loaded:
            disc = ", ".join(lib.get("discovered_vars") or [])
            reached = ", ".join(lib.get("vars") or [])
            lines.append(
                "| {name} | {path} | {rev} | {disc} | {reached} |".format(
                    name=_md_cell(lib.get("name")),
                    path=_md_cell(lib.get("path")),
                    rev=_md_cell(lib.get("revision")),
                    disc=_md_cell(disc or None),
                    reached=_md_cell(reached or None),
                )
            )
        lines.append("")
    if calls:
        lines.extend(
            [
                "| Call | Status | Source | Call chain |",
                "| --- | --- | --- | --- |",
            ]
        )
        for call in calls:
            src_path = call.get("source_path") or "Jenkinsfile"
            loc = f"{src_path}:{call.get('line')}:{call.get('col')}"
            chain = " -> ".join(call.get("chain") or [])
            lines.append(
                "| {name} | {status} | {loc} | {chain} |".format(
                    name=_md_cell(call.get("name")),
                    status=call.get("status") or "—",
                    loc=_md_cell(loc),
                    chain=_md_cell(chain or None),
                )
            )
        lines.append("")
    return lines


def _finding_location(f: dict) -> str:
    """Findings at line 0 point into the generated workflow, not the source."""
    if f["line"] == 0:
        return "(generated workflow)"
    if f.get("source_path"):
        return f"({f['source_path']}, line {f['line']}, col {f['col']})"
    return f"(line {f['line']}, col {f['col']})"


def _fmt_yaml(v: dict) -> str:
    if v.get("ok") is True:
        return "✅ passes (`yaml.safe_load`)"
    if v.get("ok") is False:
        return f"❌ failed: {v.get('error')}"
    return f"— {v.get('note', 'not run')}"


def _fmt_actionlint(v: dict) -> str:
    if not v.get("available"):
        return "— not available on PATH (linting skipped)"
    version = v.get("version", "")
    suffix = f", {version}" if version else ""
    if v.get("ok") is True:
        return f"✅ passes (exit 0{suffix})"
    if v.get("ok") is False:
        return f"❌ failed (exit {v.get('exit_code')}{suffix}): {_short(v.get('output', ''), 160)}"
    return f"— {v.get('note', 'not run')}"


def _fmt_runtime(v: dict) -> str:
    note = v.get("note", "not performed")
    return f"⚠️ {note}"


def _short(text: str, limit: int = _TRUNCATE) -> str:
    text = text.replace("\n", " ⏎ ")
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
