"""Console summary and a self-contained HTML report for a run."""

from __future__ import annotations

import html
from datetime import datetime
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
:root{color-scheme:light;--bg:#fff;--card:#fff;--sunk:#eef6f8;--text:#122228;--muted:#4c626b;
--border:#dbe3e6;--track:#19323b;--ok:#21763c;--ok-bg:#e4fbe7;--bad:#be2323;--bad-bg:#ffedec;
--warn:#a75000;--warn-bg:#fff3d8;--skip:#54676e;--skip-bg:#e9f0f2;--stop-passed:#25984d;
--stop-failed:#d42325;--stop-error:#e78c08;--stop-skipped:#7c8d93}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#0f1619;--card:#121b1e;
--sunk:#162024;--text:#e6ecef;--muted:#a1b5bd;--border:#28353a;--track:#b1c1c7;--ok:#6fd087;
--ok-bg:#1a3520;--bad:#fb817f;--bad-bg:#4a2322;--warn:#eeb154;--warn-bg:#402c12;--skip:#a1b5bd;
--skip-bg:#263033;--stop-passed:#4ac06c;--stop-failed:#f4514f;--stop-error:#f7ac4d;
--stop-skipped:#65747a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.5 "Libre Franklin","Segoe UI",system-ui,sans-serif;font-variant-numeric:tabular-nums}
header{padding:20px 24px 4px;max-width:1100px;margin:0 auto}
header h1{margin:0;font-size:22px;line-height:1.25}header p{margin:4px 0 0;color:var(--muted)}
main{max-width:1100px;margin:0 auto;padding:12px 24px 32px}
.track{position:relative;display:flex;justify-content:space-between;align-items:center;gap:2px;
height:16px;max-width:320px;margin:12px 0 0}
.track::before{content:"";position:absolute;left:0;right:0;top:7px;height:2px;background:var(--track)}
.stop{position:relative;flex:0 1 10px;min-width:4px;height:10px;border-radius:50%;
box-shadow:0 0 0 2px var(--bg)}
.stop.passed{background:var(--stop-passed)}.stop.skipped{background:var(--stop-skipped)}
.stop.failed{background:var(--stop-failed);border-radius:2px;transform:rotate(45deg) scale(.86)}
.stop.error{background:var(--stop-error);border-radius:2px;transform:scale(.86)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin-bottom:20px}
.tile{background:var(--card);border-radius:6px;padding:12px 16px;border:1px solid var(--border)}
.tile b{display:block;font-size:24px;line-height:1.2;background:none}
.tile span{color:var(--muted);font-size:14px}
details{background:var(--card);border-radius:6px;margin-bottom:12px;border:1px solid var(--border)}
summary{cursor:pointer;padding:12px 20px;display:flex;gap:12px;align-items:center;list-style:none}
summary::-webkit-details-marker{display:none}summary:hover{background:var(--sunk);border-radius:6px}
.body{padding:0 20px 16px}.muted{color:var(--muted)}
.badge{border-radius:3px;padding:1px 8px;font-size:13px;font-weight:600;white-space:nowrap}
b.passed,b.failed,b.error,b.skipped{background:none}
.passed{color:var(--ok);background:var(--ok-bg)}.failed{color:var(--bad);background:var(--bad-bg)}
.error{color:var(--warn);background:var(--warn-bg)}.skipped{color:var(--skip);background:var(--skip-bg)}
p.error{background:none;color:var(--bad)}
.req{background:var(--sunk);border-radius:6px;padding:8px 12px;margin:4px 0 8px;font-size:16px}
.check{border-top:1px solid var(--border);padding-top:8px;margin-top:8px}
.check h4{margin:4px 0;display:flex;gap:8px;align-items:center;font-size:15px}
h5{margin:12px 0 4px;font-size:14px}.scroll{overflow-x:auto}
table{border-collapse:collapse;font-size:13px;min-width:50%}
th,td{border-bottom:1px solid var(--border);padding:6px 10px;text-align:left}
th{color:var(--muted);font-weight:600;border-bottom:2px solid var(--track)}
ul{margin:4px 0;padding-left:20px}li{margin:2px 0}
"""


def _when(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y, %H:%M UTC")
    except (TypeError, ValueError):
        return _e(value)


def html_report(result: RunResult) -> str:
    counts = result.counts()
    tiles = "".join(
        f"<div class='tile'><b class='{k}'>{v}</b><span>{_LABELS[k]}</span></div>"
        for k, v in counts.items()
    )
    kind = "Baseline" if result.mode == "baseline" else "Test run"
    track = "".join(f"<span class='stop {s.status}'></span>" for s in result.scenarios)
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
        f"<p>{kind} · {_LABELS.get(result.status, result.status)} · {_when(result.started_at)}</p>"
        f"<div class='track' role='img' aria-label='Result of each scenario'>{track}</div>"
        "</header>"
        f"<main><div class='tiles'>{tiles}</div>{''.join(sections)}</main></body></html>"
    )


def write_report(result: RunResult, run_dir: Path) -> Path:
    path = run_dir / "report.html"
    path.write_text(html_report(result), encoding="utf-8")
    return path
