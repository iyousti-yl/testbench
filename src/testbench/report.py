"""Console summary and a self-contained HTML report for a run."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from testbench.checks import ERROR, FAILED, PASSED, SKIPPED
from testbench.runner import RunResult

_LABELS = {PASSED: "Passed", FAILED: "Failed", ERROR: "Error", SKIPPED: "Not tested"}
_SYMBOLS = {PASSED: "✓", FAILED: "✗", ERROR: "!", SKIPPED: "–"}


def console_summary(result: RunResult) -> str:
    lines = [f"{result.project} / {result.suite} ({result.mode})", ""]
    for s in result.scenarios:
        lines.append(f" {_SYMBOLS[s.status]} {s.name}  [{_LABELS[s.status]}]")
        if s.message:
            lines.append(f"     {s.message}")
        for c in s.checks:
            if c.error:
                lines.append(f"     {_SYMBOLS[c.status]} {c.name}: {c.error}")
            for o in c.outcomes:
                if o.status != PASSED or result.mode == "baseline":
                    lines.append(f"     {_SYMBOLS[o.status]} {c.name}: {o.message}")
    counts = result.counts()
    lines += ["", "  ".join(f"{_LABELS[k]}: {v}" for k, v in counts.items())]
    return "\n".join(lines)


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _table(records: list[dict[str, Any]]) -> str:
    if not records:
        return ""
    columns = list(records[0].keys())
    head = "".join(f"<th>{_e(c)}</th>" for c in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{_e(r.get(c))}</td>" for c in columns) + "</tr>" for r in records
    )
    table = f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    return f"<div class='scroll'>{table}</div>"


def _details(details: dict[str, Any]) -> str:
    parts = []
    if details.get("failing_rows"):
        rows = [{**d["row"], "breaks": "; ".join(d["broken"])} for d in details["failing_rows"]]
        parts.append("<h5>Rows that break the rule</h5>" + _table(rows))
    if details.get("rows"):
        parts.append("<h5>Rows returned</h5>" + _table(details["rows"]))
    if details.get("changed"):
        rows = []
        for change in details["changed"]:
            key = ", ".join(f"{k}={v}" for k, v in change["key"].items())
            if not change["differences"]:
                rows.append(
                    {"row": key, "column": "(values changed)", "expected": "", "actual": ""}
                )
            for d in change["differences"]:
                rows.append({"row": key, **d})
        parts.append("<h5>Changed values</h5>" + _table(rows))
    if details.get("added"):
        parts.append("<h5>Unexpected rows</h5>" + _table(details["added"]))
    if details.get("removed"):
        parts.append("<h5>Missing rows</h5>" + _table(details["removed"]))
    elif details.get("removed_count"):
        parts.append(
            f"<p class='muted'>{details['removed_count']} rows from the baseline are missing "
            "(values are not stored for sensitive connections).</p>"
        )
    if details.get("totals"):
        parts.append("<h5>Column totals</h5>" + _table(details["totals"]))
    for key in ("missing_columns", "extra_columns"):
        if details.get(key):
            label = "Missing columns" if key == "missing_columns" else "New columns"
            parts.append(f"<p><strong>{label}:</strong> {_e(', '.join(details[key]))}</p>")
    return "".join(parts)


_CSS = """
:root{--bg:#f5f6f7;--card:#fff;--text:#1d2d3e;--muted:#556b82;--border:#d9d9d9;
--brand:#0070f2;--ok:#256f3a;--ok-bg:#f5fae5;--bad:#aa0808;--bad-bg:#ffeaf4;
--warn:#e76500;--warn-bg:#fff8d6;--skip:#5b738b;--skip-bg:#eff1f2}
@media (prefers-color-scheme:dark){:root{--bg:#12171c;--card:#1d232a;--text:#eaecee;
--muted:#a9b4be;--border:#3a434c;--brand:#4db1ff;--ok:#6dd58c;--ok-bg:#1d3324;
--bad:#ff8888;--bad-bg:#3d1c22;--warn:#ffab4d;--warn-bg:#3b2d16;--skip:#a9b4be;--skip-bg:#2a3138}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:14px/1.5 "72","Segoe UI",system-ui,sans-serif}
header{background:var(--card);border-bottom:1px solid var(--border);padding:16px 24px}
header h1{margin:0;font-size:20px}header p{margin:4px 0 0;color:var(--muted)}
main{max-width:1100px;margin:0 auto;padding:24px 16px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:24px}
.tile{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:12px 16px}
.tile b{display:block;font-size:28px;background:none}.tile span{color:var(--muted)}
details{background:var(--card);border:1px solid var(--border);border-radius:12px;margin-bottom:12px}
summary{cursor:pointer;padding:12px 16px;display:flex;gap:12px;align-items:center;list-style:none}
summary::-webkit-details-marker{display:none}
.body{padding:0 16px 16px}.muted{color:var(--muted)}
.badge{border-radius:999px;padding:2px 10px;font-size:12px;font-weight:600;white-space:nowrap}
.passed{color:var(--ok);background:var(--ok-bg)}.failed{color:var(--bad);background:var(--bad-bg)}
.error{color:var(--warn);background:var(--warn-bg)}.skipped{color:var(--skip);background:var(--skip-bg)}
.req{border-left:3px solid var(--brand);padding:4px 12px;margin:8px 0}
.check{border-top:1px solid var(--border);padding-top:8px;margin-top:8px}
.check h4{margin:4px 0;display:flex;gap:8px;align-items:center;font-size:14px}
h5{margin:12px 0 4px;font-size:13px}.scroll{overflow-x:auto}
table{border-collapse:collapse;font-size:13px;min-width:50%}
th,td{border:1px solid var(--border);padding:4px 8px;text-align:left}th{background:var(--bg)}
ul{margin:4px 0;padding-left:20px}
"""


def html_report(result: RunResult) -> str:
    counts = result.counts()
    tiles = "".join(
        f"<div class='tile'><b class='{k}'>{v}</b><span>{_LABELS[k]}</span></div>"
        for k, v in counts.items()
    )
    sections = []
    for s in result.scenarios:
        checks_html = []
        for c in s.checks:
            items = "".join(
                f"<li><span class='badge {o.status}'>{_LABELS[o.status]}</span> "
                f"{_e(o.expectation)}: {_e(o.message)}{_details(o.details)}</li>"
                for o in c.outcomes
            )
            error = f"<p class='error'>{_e(c.error)}</p>" if c.error else ""
            checks_html.append(
                f"<div class='check'><h4><span class='badge {c.status}'>{_LABELS[c.status]}</span>"
                f"{_e(c.name)}</h4>{error}<ul>{items}</ul></div>"
            )
        requirement = f"<div class='req'>{_e(s.requirement)}</div>" if s.requirement else ""
        meta = []
        if s.tags:
            meta.append("Tags: " + _e(", ".join(s.tags)))
        if s.selected_rows is not None:
            meta.append(f"{s.selected_rows} matching records")
        open_attr = " open" if s.status in (FAILED, ERROR) else ""
        sections.append(
            f"<details{open_attr}><summary><span class='badge {s.status}'>{_LABELS[s.status]}"
            f"</span><strong>{_e(s.name)}</strong></summary><div class='body'>{requirement}"
            f"<p class='muted'>{' · '.join(meta)}</p>"
            f"{f'<p>{_e(s.message)}</p>' if s.message else ''}"
            f"{f'<p class=muted>{_e(s.description)}</p>' if s.description else ''}"
            f"{''.join(checks_html)}</div></details>"
        )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{_e(result.suite)} test report</title><style>{_CSS}</style></head><body>"
        f"<header><h1>{_e(result.project)} · {_e(result.suite)}</h1>"
        f"<p>{_LABELS.get(result.status, result.status)} · started {_e(result.started_at)}"
        f" · finished {_e(result.finished_at)}</p></header>"
        f"<main><div class='tiles'>{tiles}</div>{''.join(sections)}</main></body></html>"
    )


def write_report(result: RunResult, run_dir: Path) -> Path:
    path = run_dir / "report.html"
    path.write_text(html_report(result), encoding="utf-8")
    return path
