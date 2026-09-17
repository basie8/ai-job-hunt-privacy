"""Render the operations dashboard as a standalone HTML page.

The data is baked in at generation time rather than fetched at view time: the
artifact sandbox blocks outbound requests, and the underlying numbers only change
when a scheduled run changes them, so republishing on that same cadence is as
live as the data itself. The page states its own age and says so loudly when it
has gone stale, because a dashboard that silently shows yesterday is the exact
failure this system is built to avoid.
"""

from __future__ import annotations

import json
from typing import Any, Dict

# Validated against scripts/validate_palette.js: all six checks pass in both
# modes for the categorical pair (#2a78d6/#eb6834 light, #3987e5/#d95926 dark).
STYLE = """
:root {
  --ground:   #faf8f4;
  --surface:  #ffffff;
  --surface-2:#f3f0e9;
  --ink:      #16150f;
  --ink-2:    #5a584f;
  --ink-3:    #8a877c;
  --line:     #e3ded2;
  --line-2:   #cfc9ba;
  --accent:   #2a78d6;
  --accent-2: #eb6834;
  --good:     #1baf7a;
  --warn:     #eda100;
  --crit:     #e34948;
  --good-bg:  #e8f7f1;
  --warn-bg:  #fdf3dd;
  --crit-bg:  #fceceb;
  --shadow:   0 1px 2px rgba(22,21,15,.05), 0 8px 24px -16px rgba(22,21,15,.18);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ground:   #17160f;
    --surface:  #201f1a;
    --surface-2:#292820;
    --ink:      #f4f2ea;
    --ink-2:    #a9a597;
    --ink-3:    #7d7a6e;
    --line:     #343228;
    --line-2:   #47443a;
    --accent:   #3987e5;
    --accent-2: #d95926;
    --good:     #199e70;
    --warn:     #c98500;
    --crit:     #e66767;
    --good-bg:  #12241d;
    --warn-bg:  #2a2212;
    --crit-bg:  #2d1a19;
    --shadow:   0 1px 2px rgba(0,0,0,.3), 0 8px 24px -16px rgba(0,0,0,.6);
  }
}
:root[data-theme="dark"] {
  --ground:   #17160f;
  --surface:  #201f1a;
  --surface-2:#292820;
  --ink:      #f4f2ea;
  --ink-2:    #a9a597;
  --ink-3:    #7d7a6e;
  --line:     #343228;
  --line-2:   #47443a;
  --accent:   #3987e5;
  --accent-2: #d95926;
  --good:     #199e70;
  --warn:     #c98500;
  --crit:     #e66767;
  --good-bg:  #12241d;
  --warn-bg:  #2a2212;
  --crit-bg:  #2d1a19;
  --shadow:   0 1px 2px rgba(0,0,0,.3), 0 8px 24px -16px rgba(0,0,0,.6);
}

* { box-sizing: border-box; }
body {
  margin: 0; background: var(--ground); color: var(--ink);
  font-family: "Source Sans 3", ui-sans-serif, system-ui, -apple-system, sans-serif;
  font-size: 15px; line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 1180px; margin: 0 auto; padding-inline: 20px; padding-block: 0 56px; }
h1, h2, h3 { font-family: Archivo, ui-sans-serif, system-ui, sans-serif; margin: 0; text-wrap: balance; }
h1 { font-size: 27px; font-weight: 700; letter-spacing: -.02em; }
h2 { font-size: 13px; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; color: var(--ink-2); }
h3 { font-size: 15px; font-weight: 600; }
.mono { font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
        font-variant-numeric: tabular-nums; }
a { color: var(--accent); }

/* ---- status ribbon: the first thing read, never subtle ---- */
.ribbon { border-bottom: 1px solid var(--line); }
.ribbon-inner {
  max-width: 1180px; margin: 0 auto; padding: 18px 20px;
  display: flex; flex-wrap: wrap; gap: 14px 22px; align-items: center;
}
.ribbon.ok   { background: var(--good-bg); border-bottom-color: var(--good); }
.ribbon.warning { background: var(--warn-bg); border-bottom-color: var(--warn); }
.ribbon.critical { background: var(--crit-bg); border-bottom-color: var(--crit); }
.dot { width: 11px; height: 11px; border-radius: 50%; flex: none; }
.ok .dot { background: var(--good); }
.warning .dot { background: var(--warn); }
.critical .dot { background: var(--crit); }
.ribbon-label { font-family: Archivo, sans-serif; font-weight: 700;
                letter-spacing: .08em; text-transform: uppercase; font-size: 12px; }
.ribbon-meta { color: var(--ink-2); font-size: 13px; margin-left: auto; }
.paper {
  font-family: Archivo, sans-serif; font-weight: 700; font-size: 11px;
  letter-spacing: .1em; padding: 3px 9px; border-radius: 4px;
  border: 1.5px solid currentColor; color: var(--ink-2); white-space: nowrap;
}

/* ---- problems: every error, in one place, never collapsed away ---- */
.problems { display: grid; gap: 8px; margin-top: 18px; }
.problem {
  display: grid; grid-template-columns: auto 1fr; gap: 12px; align-items: start;
  padding: 11px 14px; border-radius: 7px; background: var(--surface);
  border: 1px solid var(--line); border-left-width: 4px;
}
.problem.critical { border-left-color: var(--crit); }
.problem.warning  { border-left-color: var(--warn); }
.problem .tag {
  font-size: 11px; letter-spacing: .07em; text-transform: uppercase;
  font-weight: 700; padding-top: 2px; white-space: nowrap;
}
.problem.critical .tag { color: var(--crit); }
.problem.warning .tag  { color: var(--warn); }

/* ---- phase rail: a real sequence, so numbering is information ---- */
.rail { display: grid; grid-template-columns: repeat(6, 1fr); gap: 3px; margin-top: 10px; }
.phase { padding: 10px 11px; background: var(--surface); border: 1px solid var(--line);
         border-radius: 5px; min-width: 0; }
.phase .n { font-size: 11px; font-weight: 700; color: var(--ink-3); }
.phase .nm { font-size: 13px; font-weight: 600; margin-top: 1px;
             overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.phase .gate { font-size: 11px; color: var(--ink-3); margin-top: 3px; line-height: 1.35; }
.phase.done { background: var(--good-bg); border-color: var(--good); }
.phase.done .n { color: var(--good); }
.phase.now  { background: var(--crit-bg); border-color: var(--crit); border-width: 2px; }
.phase.now .n { color: var(--crit); }

/* ---- panels ---- */
.grid { display: grid; gap: 16px; margin-top: 16px; }
.cols-2 { grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); }
.cols-3 { grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
.panel { background: var(--surface); border: 1px solid var(--line); border-radius: 9px;
         padding: 18px; box-shadow: var(--shadow); min-width: 0; }
.panel-head { display: flex; align-items: baseline; justify-content: space-between;
              gap: 12px; margin-bottom: 14px; }
.panel-note { font-size: 12px; color: var(--ink-3); }
.src { font-size: 11px; color: var(--ink-3); margin-top: 14px;
       padding-top: 10px; border-top: 1px solid var(--line); }

/* ---- the two non-data states, deliberately unalike ---- */
.state { border-radius: 7px; padding: 16px; font-size: 14px; }
.state-empty {
  border: 1px dashed var(--line-2); background: var(--surface-2); color: var(--ink-2);
}
.state-empty .st { font-weight: 600; color: var(--ink); display: block; margin-bottom: 4px; }
.state-error {
  border: 1px solid var(--crit); border-left-width: 4px; background: var(--crit-bg); color: var(--ink);
}
.state-error .st { font-weight: 700; color: var(--crit); display: block; margin-bottom: 4px;
                   text-transform: uppercase; letter-spacing: .06em; font-size: 12px; }

/* ---- figures ---- */
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 2px;
         background: var(--line); border: 1px solid var(--line); border-radius: 7px; overflow: hidden; }
.tile { background: var(--surface); padding: 13px 14px; }
.tile .k { font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: var(--ink-3); }
.tile .v { font-size: 23px; font-weight: 700; line-height: 1.2; margin-top: 2px; }
.tile .s { font-size: 12px; color: var(--ink-3); }
.tile .v.pending { color: var(--ink-3); font-size: 16px; font-weight: 600; }

.bar-track { height: 26px; border-radius: 5px; overflow: hidden; display: flex; gap: 2px;
             background: var(--line); }
.bar-seg { height: 100%; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 18px; margin-top: 12px; font-size: 13px; }
.legend span.sw { width: 11px; height: 11px; border-radius: 3px; display: inline-block;
                  vertical-align: -1px; margin-right: 6px; }

table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; font-weight: 600; color: var(--ink-2); font-size: 11px;
     letter-spacing: .06em; text-transform: uppercase; padding: 0 8px 7px 0; }
td { padding: 7px 8px 7px 0; border-top: 1px solid var(--line); vertical-align: top; }
td.num { text-align: right; padding-right: 14px; }
.scroll { overflow-x: auto; }
.pill { display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 7px;
        border-radius: 4px; letter-spacing: .04em; }
.pill.done  { background: var(--good-bg); color: var(--good); }
.pill.block { background: var(--crit-bg); color: var(--crit); }
.pill.out   { background: var(--surface-2); color: var(--ink-2); }
.pill.prog  { background: color-mix(in srgb, var(--accent) 14%, transparent); color: var(--accent); }

.funnel-row { display: grid; grid-template-columns: 1fr; gap: 3px; margin-bottom: 11px; }
.funnel-label { display: flex; justify-content: space-between; gap: 10px; font-size: 13px; }
.funnel-bar { height: 12px; border-radius: 0 4px 4px 0; background: var(--accent); min-width: 2px; }

footer { margin-top: 34px; padding-top: 18px; border-top: 1px solid var(--line);
         font-size: 12px; color: var(--ink-3); }
@media (max-width: 760px) {
  .rail { grid-template-columns: repeat(2, 1fr); }
  h1 { font-size: 22px; }
  .ribbon-meta { margin-left: 0; width: 100%; }
}
@media (prefers-reduced-motion: no-preference) {
  .panel { transition: border-color .15s ease; }
}
"""


def _esc(text: Any) -> str:
    return (
        str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _state_block(section: Dict[str, Any], what: str) -> str:
    """Render the difference between 'nothing yet' and 'something broke'."""
    if section["status"] == "error":
        data = section.get("data") or {}
        trace = data.get("traceback", "")
        return (
            f'<div class="state state-error"><span class="st">Failed to read</span>'
            f"{_esc(section['reason'])}"
            + (f'<div class="mono" style="font-size:11px;margin-top:8px;opacity:.8">'
               f"{_esc(trace.strip().splitlines()[-1] if trace.strip() else '')}</div>" if trace else "")
            + "</div>"
        )
    return (
        f'<div class="state state-empty"><span class="st">No {what} yet</span>'
        f"{_esc(section['reason'])}</div>"
    )


def _tasks_panel(section: Dict[str, Any]) -> str:
    if section["status"] != "ok":
        return _state_block(section, "task data")
    data = section["data"]
    summary, buckets = data["summary"], data["buckets"]
    order = [
        ("done", "Complete", "var(--good)"),
        ("in_progress", "In progress", "var(--accent)"),
        ("unverified", "Done, unverifiable", "var(--accent-2)"),
        ("outstanding", "Outstanding", "var(--line-2)"),
        ("blocked", "Blocked", "var(--crit)"),
    ]
    segments, legend = [], []
    for key, label, color in order:
        count = len(buckets[key])
        if count:
            segments.append(
                f'<div class="bar-seg" style="background:{color};flex:{count}" '
                f'title="{label}: {count}"></div>'
            )
        legend.append(
            f'<div><span class="sw" style="background:{color}"></span>{label} '
            f'<strong class="mono">{count}</strong></div>'
        )

    rows = []
    for key, label, _ in (("blocked", "Blocked", ""), ("in_progress", "In progress", ""),
                          ("outstanding", "Outstanding", "")):
        for task in buckets[key][:14]:
            pill = {"blocked": "block", "in_progress": "prog", "outstanding": "out"}[key]
            rows.append(
                f"<tr><td class='mono'>{_esc(task['id'])}</td>"
                f"<td>{_esc(task['title'])}</td>"
                f"<td><span class='pill {pill}'>{_esc(label)}</span></td>"
                f"<td style='color:var(--ink-3)'>{_esc(task['detail'] or task['notes'])[:80]}</td></tr>"
            )

    stale_warning = ""
    if buckets["stale"]:
        stale_warning = (
            f'<div class="state state-error" style="margin-bottom:14px">'
            f'<span class="st">{len(buckets["stale"])} stale claim(s)</span>'
            "A task is marked done but its verification fails. Either the work regressed or "
            "the roadmap is wrong.</div>"
        )

    return f"""{stale_warning}
      <div class="bar-track">{''.join(segments)}</div>
      <div class="legend">{''.join(legend)}</div>
      <div class="scroll" style="margin-top:16px">
        <table><thead><tr><th>ID</th><th>Task</th><th>State</th><th>Check</th></tr></thead>
        <tbody>{''.join(rows)}</tbody></table>
      </div>
      <div class="src mono">{_esc(section['source'])} &middot; {summary['total']} tasks &middot;
        {summary['percent_complete']}% verified complete &middot;
        every task accounted for: {'yes' if data['accounted_for'] else 'NO'}</div>"""


def _funnel_panel(section: Dict[str, Any]) -> str:
    if section["status"] != "ok":
        return _state_block(section, "pipeline runs")
    data = section["data"]
    stages = data["stages"]
    top = max((s["count"] for s in stages), default=0) or 1
    rows = []
    previous = None
    for stage in stages:
        width = stage["count"] / top * 100
        lost = "" if previous is None else f" &minus;{previous - stage['count']}"
        rows.append(
            f'<div class="funnel-row"><div class="funnel-label"><span>{_esc(stage["label"])}</span>'
            f'<span class="mono"><strong>{stage["count"]}</strong>'
            f'<span style="color:var(--ink-3)">{lost}</span></span></div>'
            f'<div class="funnel-bar" style="width:{width:.1f}%"></div></div>'
        )
        previous = stage["count"]

    refusals = data["refusals"]
    refusal_rows = "".join(
        f"<tr><td class='mono'>{_esc(code)}</td><td class='num mono'>{count}</td></tr>"
        for code, count in list(refusals.items())[:10]
    ) or "<tr><td colspan='2' style='color:var(--ink-3)'>No hard refusals recorded.</td></tr>"

    malformed = ""
    if data.get("malformed_lines"):
        malformed = (
            f'<div class="state state-error" style="margin-top:14px">'
            f'<span class="st">{data["malformed_lines"]} unreadable audit lines</span>'
            "Skipped while counting. The audit log may be corrupt.</div>"
        )

    return f"""{''.join(rows)}
      <h3 style="margin-top:18px;font-size:13px">Why trades were refused</h3>
      <div class="scroll"><table><tbody>{refusal_rows}</tbody></table></div>
      {malformed}
      <div class="src mono">{_esc(section['source'])}</div>"""


def _equity_svg(points, width=560, height=170) -> str:
    if len(points) < 2:
        return ""
    pad_l, pad_r, pad_t, pad_b = 44, 14, 14, 26
    values = [p["cumulative_r"] for p in points]
    lo, hi = min(min(values), 0.0), max(max(values), 0.0)
    if hi == lo:
        hi = lo + 1.0
    span = hi - lo
    inner_w, inner_h = width - pad_l - pad_r, height - pad_t - pad_b

    def x(i):
        return pad_l + (i / (len(points) - 1)) * inner_w

    def y(v):
        return pad_t + (hi - v) / span * inner_h

    line = " ".join(f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values))
    area = f"{line} L{x(len(values) - 1):.1f},{y(0):.1f} L{x(0):.1f},{y(0):.1f} Z"
    ticks = "".join(
        f'<line x1="{pad_l}" y1="{y(v):.1f}" x2="{width - pad_r}" y2="{y(v):.1f}" '
        f'stroke="var(--line)" stroke-width="1"/>'
        f'<text x="{pad_l - 8}" y="{y(v) + 4:.1f}" text-anchor="end" font-size="11" '
        f'fill="var(--ink-3)" class="mono">{v:+.1f}R</text>'
        for v in (hi, (hi + lo) / 2, lo)
    )
    last_x, last_y = x(len(values) - 1), y(values[-1])
    return f"""<svg viewBox="0 0 {width} {height}" width="100%" height="{height}"
        role="img" aria-label="Cumulative R over closed trades" style="overflow:visible">
      {ticks}
      <line x1="{pad_l}" y1="{y(0):.1f}" x2="{width - pad_r}" y2="{y(0):.1f}"
            stroke="var(--line-2)" stroke-width="1" stroke-dasharray="3 3"/>
      <path d="{area}" fill="var(--accent)" fill-opacity="0.13"/>
      <path d="{line}" fill="none" stroke="var(--accent)" stroke-width="2"
            stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="4.5" fill="var(--accent)"
              stroke="var(--surface)" stroke-width="2"/>
      <text x="{last_x:.1f}" y="{last_y - 12:.1f}" text-anchor="end" font-size="12"
            font-weight="700" fill="var(--ink)" class="mono">{values[-1]:+.2f}R</text>
    </svg>"""


def _trading_panel(section: Dict[str, Any]) -> str:
    if section["status"] != "ok":
        return _state_block(section, "closed trades") + (
            '<div class="src mono">' + _esc(section["source"]) + "</div>"
        )
    data = section["data"]
    summary = data["summary"]
    cal = data["calibration"]
    tiles = [
        ("Closed trades", str(data["closed_n"]), data["learning_status"].replace("_", " ")),
        ("Win rate", f"{summary['win_rate']:.0%}" if summary["win_rate"] is not None else "—",
         f"{summary['wins']} of {summary['closed']}"),
        ("Expectancy", f"{summary['expectancy_r']:+.2f}R" if summary["expectancy_r"] is not None else "—",
         f"total {summary['total_r']:+.1f}R"),
        ("Max drawdown", f"{data['max_drawdown_r']:+.2f}R", "peak to trough"),
        ("Calibration", f"{cal['brier']:.3f}" if cal["brier"] is not None else "—", "Brier score"),
        ("Conviction ×", f"{data['conviction_multiplier']:.2f}", "learned clamp"),
    ]
    tile_html = "".join(
        f'<div class="tile"><div class="k">{_esc(k)}</div>'
        f'<div class="v mono">{_esc(v)}</div><div class="s">{_esc(s)}</div></div>'
        for k, v, s in tiles
    )
    setup_rows = "".join(
        f"<tr><td class='mono'>{_esc(name)}</td>"
        f"<td class='num mono'>{stat['n']}</td>"
        f"<td class='num mono'>{(stat['win_rate'] or 0):.0%}</td>"
        f"<td class='num mono'>{(stat['expectancy_r'] or 0):+.2f}R</td>"
        f"<td class='num mono'>{data['size_multipliers'].get(name, 1.0):.2f}</td></tr>"
        for name, stat in data["setups"].items()
    ) or "<tr><td colspan='5' style='color:var(--ink-3)'>No closed trades by setup yet.</td></tr>"

    return f"""<div class="tiles">{tile_html}</div>
      <div style="margin-top:18px">{_equity_svg(data['equity_curve'])}</div>
      <h3 style="margin-top:18px;font-size:13px">Performance by setup</h3>
      <div class="scroll"><table>
        <thead><tr><th>Setup</th><th class="num">n</th><th class="num">Win</th>
        <th class="num">Expectancy</th><th class="num">Size ×</th></tr></thead>
        <tbody>{setup_rows}</tbody></table></div>
      <div class="src mono">{_esc(section['source'])}</div>"""


def render(payload: Dict[str, Any]) -> str:
    sections = payload["sections"]
    health = payload["health"]
    problems = payload["problems"]

    problem_html = "".join(
        f'<div class="problem {_esc(p["severity"])}"><span class="tag">{_esc(p["severity"])}</span>'
        f'<div><strong>{_esc(p["source"])}</strong> — {_esc(p["message"])}</div></div>'
        for p in problems
    ) or (
        '<div class="problem" style="border-left-color:var(--good)">'
        '<span class="tag" style="color:var(--good)">clear</span>'
        "<div>No errors, no warnings, no stale claims.</div></div>"
    )

    phase_section = sections["phase"]
    if phase_section["status"] == "ok":
        current = phase_section["data"]["current"]
        rail = "".join(
            f'<div class="phase {"done" if p["complete"] else ""} '
            f'{"now" if p["number"] == current["number"] else ""}">'
            f'<div class="n">PHASE {p["number"]}</div>'
            f'<div class="nm">{_esc(p["name"])}</div>'
            f'<div class="gate">{_esc(p["gate"])}</div></div>'
            for p in phase_section["data"]["phases"]
        )
        phase_block = f'<div class="rail">{rail}</div>'
    else:
        phase_block = _state_block(phase_section, "phase data")

    check = sections["selfcheck"]
    if check["status"] == "ok":
        d = check["data"]
        passed = d["total"] - d["failed"] - d["warned"]
        check_block = (
            f'<div class="tiles"><div class="tile"><div class="k">Passing</div>'
            f'<div class="v mono" style="color:var(--good)">{passed}</div>'
            f'<div class="s">of {d["total"]} checks</div></div>'
            f'<div class="tile"><div class="k">Failing</div>'
            f'<div class="v mono" style="color:{"var(--crit)" if d["failed"] else "var(--ink-3)"}">'
            f'{d["failed"]}</div><div class="s">components</div></div></div>'
        )
        failing = "".join(
            f"<tr><td class='mono'>{_esc(r['component'])}</td><td>{_esc(r['check'])}</td>"
            f"<td style='color:var(--crit)'>{_esc(r['detail'])}</td></tr>"
            for r in d["results"] if r["status"] == "FAIL"
        )
        if failing:
            check_block += (
                '<div class="scroll" style="margin-top:14px"><table><thead><tr>'
                "<th>Component</th><th>Check</th><th>Detail</th></tr></thead>"
                f"<tbody>{failing}</tbody></table></div>"
            )
    else:
        check_block = _state_block(check, "self-check results")

    health_section = sections["data_health"]
    if health_section["status"] == "ok":
        rows = "".join(
            f"<tr><td class='mono'>{_esc(s['timeframe'])}</td>"
            f"<td class='num mono'>{s['bars']}</td>"
            f"<td class='num mono'>{s['age_min']:.0f} min</td>"
            f"<td class='num mono'>{_esc(s['last_close'])}</td></tr>"
            for s in health_section["data"]["series"]
        )
        feed_block = (
            '<div class="scroll"><table><thead><tr><th>TF</th><th class="num">Bars</th>'
            '<th class="num">Age</th><th class="num">Last close</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div>"
        )
    else:
        feed_block = _state_block(health_section, "candles")

    runs = sections["runs"]
    if runs["status"] == "ok":
        run_rows = ""
        for routine in runs["data"]["routines"]:
            gaps = len(routine["missed"]) + len(routine["errors"])
            pill = "block" if gaps else "done"
            label = f"{gaps} gap{'s' if gaps != 1 else ''}" if gaps else "complete"
            run_rows += (
                f"<tr><td class='mono'>{_esc(routine['routine'])}</td>"
                f"<td class='num mono'>{routine['recorded']}/{routine['expected']}</td>"
                f"<td><span class='pill {pill}'>{_esc(label)}</span></td></tr>"
            )
        missed = runs["data"]["missed_total"] + runs["data"]["error_total"]
        note = ("Every run records that it happened, on every path. A gap means a run "
                "died before reaching the pipeline." if not missed else
                f"{missed} scheduled run(s) never happened or errored — see the top of the page.")
        runs_block = (
            '<div class="scroll"><table><thead><tr><th>Routine</th>'
            '<th class="num">Ran</th><th>State</th></tr></thead><tbody>'
            + run_rows + "</tbody></table></div>"
            + f'<div class="panel-note" style="margin-top:10px">{_esc(note)}</div>'
        )
    else:
        runs_block = _state_block(runs, "recorded runs")

    config = sections["config"]
    if config["status"] == "ok":
        c = config["data"]
        stage_rows = "".join(
            f"<tr><td>{_esc(stage.replace('_', ' ').title())}</td>"
            f"<td class='mono'>{_esc(spec['model'])}</td>"
            f"<td class='mono'>{_esc(spec['effort'] or '—')}</td></tr>"
            for stage, spec in c["stages"].items()
        )
        config_block = f"""<div class="scroll"><table>
            <thead><tr><th>Stage</th><th>Model</th><th>Effort</th></tr></thead>
            <tbody>{stage_rows}</tbody></table></div>
          <div class="legend" style="margin-top:14px">
            <div>Mode <strong class="mono">{_esc(c.get('mode', 'paper')).upper()}</strong></div>
            <div>Paper account <strong class="mono">{_esc(c.get('account_currency', 'USD'))}
              {c.get('account_value', c['account_usd']):,.0f}</strong>
              <span style="color:var(--ink-3)">(${c['account_usd']:,.0f})</span></div>
            <div>Risk/trade <strong class="mono">{c['risk_per_trade_pct']:.2f}% of equity</strong>
              <span style="color:var(--ink-3)">(opening ${c['base_risk_usd']:,.0f})</span></div>
            <div>Min R:R <strong class="mono">{c['min_reward_risk']:.1f}</strong></div>
            <div>Daily stop <strong class="mono">&minus;{c['max_daily_loss_r']:.1f}R</strong></div>
            <div>Equity floor <strong class="mono">{c.get('min_equity_pct_of_start', 0):.0f}% of start</strong></div>
          </div>
          <div class="panel-note" style="margin-top:12px">
            <span class="pill {'done' if c.get('fx_live') else 'block'}">
              {'FX live' if c.get('fx_live') else 'FX fallback'}</span>
            {_esc(c.get('fx_note', 'no FX provenance recorded'))}
          </div>"""
    else:
        config_block = _state_block(config, "configuration")

    calendar = sections["calendar"]
    if calendar["status"] == "ok":
        events = calendar["data"]["upcoming"]
        event_rows = "".join(
            f"<tr><td>{_esc(e['name'])}</td><td class='mono'>{_esc(e['when'][:16].replace('T', ' '))}</td>"
            f"<td><span class='pill {'block' if e['impact'] == 'high' else 'out'}'>"
            f"{_esc(e['impact'])}</span></td></tr>"
            for e in events[:6]
        ) or "<tr><td colspan='3' style='color:var(--ink-3)'>Nothing in the next 72 hours.</td></tr>"
        calendar_block = (
            f'<div class="panel-note" style="margin-bottom:10px">Calendar confidence: '
            f'<strong>{_esc(calendar["data"]["confidence"])}</strong></div>'
            '<div class="scroll"><table><tbody>' + event_rows + "</tbody></table></div>"
        )
    else:
        calendar_block = _state_block(calendar, "calendar")

    # The blob sits inside <script>, so any "</script>" in a file path, task
    # title or exception message would break out of the tag and take the page
    # with it. These three characters only ever appear inside JSON string
    # values, and a unicode escape is valid JSON, so this is lossless -- the
    # round trip is covered by a test.
    data_json = (
        json.dumps(payload, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )

    return f"""<title>AURUM Control</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700&family=Source+Sans+3:wght@400;600&family=JetBrains+Mono:wght@400;700&display=swap">
<style>{STYLE}</style>

<div class="ribbon {health}" id="ribbon">
  <div class="ribbon-inner">
    <span class="dot"></span>
    <span class="ribbon-label" id="health-label">system {health}</span>
    <span class="paper" title="No orders are placed. Outcomes are simulated against later candles.">PAPER</span>
    <span style="color:var(--ink-2);font-size:13px" id="health-detail"></span>
    <span class="ribbon-meta mono">generated <span id="age">{_esc(payload['generated_at'])}</span></span>
  </div>
</div>

<div class="wrap">
  <div style="padding-block:24px 4px">
    <h1>AURUM &mdash; XAUUSD operations</h1>
    <div style="color:var(--ink-2);margin-top:4px">
      Signal pipeline delivery, decision process and measured performance.
      <strong>Paper trading.</strong> MT5 supplies candles only; no order is ever placed,
      and every outcome below is simulated against the candles that followed the signal.
    </div>
  </div>

  <div class="problems">{problem_html}</div>

  <h2 style="margin-top:30px">Development phase</h2>
  {phase_block}

  <div class="grid cols-2">
    <div class="panel">
      <div class="panel-head"><h2>Delivery</h2>
        <span class="panel-note">verified, not self-reported</span></div>
      {_tasks_panel(sections['tasks'])}
    </div>
    <div class="panel">
      <div class="panel-head"><h2>Decision funnel</h2>
        <span class="panel-note">how ideas reach an order</span></div>
      {_funnel_panel(sections['funnel'])}
    </div>
  </div>

  <div class="grid">
    <div class="panel">
      <div class="panel-head"><h2>Trading performance</h2>
        <span class="panel-note">simulated; R multiples, not currency</span></div>
      {_trading_panel(sections['trading'])}
    </div>
  </div>

  <div class="grid cols-3">
    <div class="panel">
      <div class="panel-head"><h2>Component health</h2></div>
      {check_block}
      <div class="src mono">{_esc(sections['selfcheck']['source'])}</div>
    </div>
    <div class="panel">
      <div class="panel-head"><h2>Candle feed</h2></div>
      {feed_block}
      <div class="src mono">{_esc(health_section['source'])}</div>
    </div>
    <div class="panel">
      <div class="panel-head"><h2>Event diary</h2></div>
      {calendar_block}
      <div class="src mono">{_esc(calendar['source'])}</div>
    </div>
    <div class="panel">
      <div class="panel-head"><h2>Scheduled runs</h2>
        <span class="panel-note">did they actually happen</span></div>
      {runs_block}
      <div class="src mono">{_esc(sections['runs']['source'])}</div>
    </div>
  </div>

  <div class="grid">
    <div class="panel">
      <div class="panel-head"><h2>Pipeline configuration</h2>
        <span class="panel-note">enforced in code, after the models</span></div>
      {config_block}
      <div class="src mono">{_esc(config['source'])}</div>
    </div>
  </div>

  <footer>
    Data baked in at generation time and republished by the scheduled runs.
    The page states its own age above and flags itself when stale &mdash; it never
    shows an old number as a current one.
  </footer>
</div>

<script id="dashboard-data" type="application/json">{data_json}</script>
<script>
(function () {{
  var payload;
  try {{
    payload = JSON.parse(document.getElementById("dashboard-data").textContent);
  }} catch (err) {{
    var ribbon = document.getElementById("ribbon");
    ribbon.className = "ribbon critical";
    document.getElementById("health-label").textContent = "dashboard data unreadable";
    document.getElementById("health-detail").textContent = String(err);
    return;
  }}

  // The page must know when it has gone stale. A dashboard quietly showing
  // yesterday's numbers is the failure mode this whole system is built against.
  var generated = new Date(payload.generated_at);
  var ageMin = (Date.now() - generated.getTime()) / 60000;
  var ageText;
  if (!isFinite(ageMin)) ageText = "generation time unreadable";
  else if (ageMin < 90) ageText = Math.round(ageMin) + " min ago";
  else if (ageMin < 2880) ageText = (ageMin / 60).toFixed(1) + " h ago";
  else ageText = (ageMin / 1440).toFixed(1) + " days ago";
  document.getElementById("age").textContent = ageText;

  var counts = {{critical: 0, warning: 0}};
  (payload.problems || []).forEach(function (p) {{ counts[p.severity] = (counts[p.severity] || 0) + 1; }});
  var detail = counts.critical + " critical, " + counts.warning + " warning";

  // Staleness outranks the baked-in health: old data cannot vouch for now.
  var STALE_MIN = 26 * 60;
  if (!isFinite(ageMin) || ageMin > STALE_MIN) {{
    document.getElementById("ribbon").className = "ribbon critical";
    document.getElementById("health-label").textContent = "data stale";
    detail = "generated " + ageText + " — the scheduled runs may have stopped. " + detail;
  }}
  document.getElementById("health-detail").textContent = detail;
}})();
</script>"""


def build_page(repo: str = ".") -> str:
    from .dashboard import build

    return render(build(repo))
