"""Aggregate verdicts + hard checks per (agent version, case), print a table, write report.html."""
import html, json, re
from collections import defaultdict
from .judge import run_checks, render_transcript


def load_runs(run_dir):
    runs = []
    for tp in sorted(run_dir.rglob("transcript.json")):
        t = json.loads(tp.read_text())
        vp = tp.parent / "verdict.json"
        v = json.loads(vp.read_text()) if vp.exists() else None
        t["_dir"], t["verdict"] = tp.parent, v
        t["checks"] = run_checks(t["case"].get("checks"), t["tool_calls"], t["turns"])
        t["status"] = run_status(t)
        runs.append(t)
    return runs


def run_status(t):
    if t.get("error") and len(t["turns"]) < 3:
        return "ERROR"
    v = t["verdict"]
    if v is None:
        return "UNJUDGED"
    if not v.get("scenario_happened", False):
        return "VOID"
    bad = any(not c["pass"] for c in t["checks"]) or any(not c["pass"] for c in v["criteria"])
    return "FAIL" if bad else "PASS"


def case_status(runs):
    """Rule (tune later): any hard-check failure = FAIL. Judge failures: >=2 of n valid runs (>=1 if n<3) = FAIL, 1 = FLAKY."""
    valid = [r for r in runs if r["status"] in ("PASS", "FAIL")]
    if not valid:
        return "UNJUDGED" if any(r["status"] == "UNJUDGED" for r in runs) else "INCONCLUSIVE"
    hard = sum(1 for r in valid if any(not c["pass"] for c in r["checks"]))
    fails = sum(1 for r in valid if r["status"] == "FAIL")
    need = 2 if len(valid) >= 3 else 1
    if hard or fails >= need:
        return "FAIL"
    return "FLAKY" if fails else "PASS"


def summarize(runs):
    groups = defaultdict(list)
    for r in runs:
        groups[(f"{r['agent']}-{r['version']}", r["case"]["id"])].append(r)
    return {k: (case_status(v), v) for k, v in groups.items()}


def print_table(summary):
    from . import ui
    by_av = defaultdict(list)
    for (av, cid), (st, rs) in sorted(summary.items()):
        by_av[av].append((cid, st, rs))
    for av, rows in by_av.items():
        counts = defaultdict(int)
        for _, st, _ in rows:
            counts[st] += 1
        order = [k for k in ("PASS", "FAIL", "FLAKY", "INCONCLUSIVE", "UNJUDGED") if counts[k]]
        ui.header(av.replace("-v", " v"), f"{len(rows)} cases")
        w = max(len(cid) for cid, _, _ in rows)
        for cid, st, rs in rows:
            valid = [r for r in rs if r["status"] in ("PASS", "FAIL")]
            note = (f"{len(rs)} run(s) waiting for a verdict" if st == "UNJUDGED" else
                    f"{sum(r['status'] == 'PASS' for r in valid)}/{len(valid)} runs passed" + (f" · {len(rs) - len(valid)} void/error" if len(rs) != len(valid) else ""))
            print(f"  {ui.status(st, 15)} {cid.ljust(w)}  {ui.c(note, 'dim')}")
        print("  " + "  ".join(ui.status(k) + f" {counts[k]}" for k in order))


CSS = """:root{--bg:#fff;--fg:#1a1a1a;--mut:#666;--line:#ddd;--pass:#1a7f37;--fail:#c62828;--flaky:#b26a00;--void:#777;--card:#f6f6f6}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#eaeaea;--mut:#9a9a9a;--line:#333;--card:#212121;--pass:#4cc38a;--fail:#ff6b6b;--flaky:#ffb454;--void:#999}}
body{font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0 auto;max-width:980px;padding:16px}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left}
.b{font-weight:700;padding:1px 8px;border-radius:10px;border:1px solid currentColor}
.PASS{color:var(--pass)}.FAIL{color:var(--fail)}.FLAKY{color:var(--flaky)}.VOID,.INCONCLUSIVE,.UNJUDGED,.ERROR{color:var(--void)}
details{background:var(--card);border-radius:8px;margin:10px 0;padding:8px 12px}summary{cursor:pointer}

.chat{display:flex;flex-direction:column;gap:6px;margin:8px 0}
.m{max-width:75%;padding:6px 10px;border-radius:14px;white-space:pre-wrap;background:var(--bg);border:1px solid var(--line)}
.m small{display:block;color:var(--mut);font-size:11px}.m.agen{align-self:flex-start;border-bottom-left-radius:4px}
.m.cust{align-self:flex-end;border-bottom-right-radius:4px;background:#d6e8ff;color:#111}
.va{border-left:3px solid var(--flaky);padding-left:8px;margin:6px 0;font-size:13px}.fl{color:var(--fail)}.m.hit{outline:2px solid #e0a800}.tc{margin-top:4px;font-size:12px}.tc code{display:block;color:var(--mut);word-break:break-all}
@media (prefers-color-scheme:dark){.m.cust{background:#1f3a5f;color:#eaeaea}}.fix{border-left:3px solid var(--flaky);padding-left:8px;margin:6px 0}
@media (max-width:600px){body{padding:12px}}"""


def esc(s):
    return html.escape(str(s))


def render_run(r):
    v = r["verdict"] or {}
    ev = {int(m) for c in v.get("criteria", []) + [{"evidence": v.get("scenario_evidence", "")}]
          for m in re.findall(r"T(\d+)", c.get("evidence", ""))}
    audio = r["_dir"].joinpath("audio.mp3").exists()
    out = [f"<details><summary>run {esc(r['run'])} <span class='b {r['status']}'>{r['status']}</span>"
           f" · ended: {esc(r['ended'])}{' · ERROR: ' + esc(r['error']) if r.get('error') else ''}</summary>"]
    if audio:
        out.append("<audio controls src='" + esc(f"{r['_dir']}/audio.mp3") + "'></audio>")
    calls = {}
    for tc in r["tool_calls"]:
        calls.setdefault(tc["turn"], []).append(tc)
    out.append("<div class='chat'>")
    for x in r["turns"]:
        seek = f" data-t='{x['t']}'" if audio and "t" in x else ""
        side = "cust" if x["role"] == "customer" else "agen"
        tools = "".join(f"<details class='tc'><summary>{esc(tc['name'])}</summary><code>{esc(json.dumps(tc['args']))}</code>"
                        f"<code>→ {esc(json.dumps(tc['result']))}</code></details>" for tc in calls.get(x["i"], []))
        out.append(f"<div class='m {side}{' hit' if x['i'] in ev else ''}'{seek}><small>T{x['i']} {esc(x['role'])}</small>"
                   f"{esc(x['text']) or '<i>(no spoken reply)</i>'}{tools}</div>")
    out.append("</div>")
    a = r.get("analysis")
    if a:
        out.append("<div class='va'><b>Voice analysis</b> (automatic hints, not verdicts)<ul>"
                   f"<li>response latency after caller stops (s): {esc(a.get('latency_s'))} · talk-over {esc(a.get('talk_over_s'))}s</li>"
                   + "".join(f"<li class='fl'>{esc(f['type'])} {('T' + str(f['turn'])) if 'turn' in f else ''} {('@' + str(f['t']) + 's') if 't' in f else ''}: {esc(f['detail'])}</li>" for f in a.get("flags", []))
                   + "".join(f"<li>STT ({esc(m['speaker'])} T{m['turn']}): said <i>{esc(m['said'])}</i> → transcribed <i>{esc(m['heard'])}</i></li>" for m in a.get("stt_mismatches", []))
                   + (f"<li>spoken form (listening model): <i>{esc(a['spoken_forms'])}</i></li>" if a.get("spoken_forms") else "") + "</ul></div>")
    out.append("<ul>")
    for c in r["checks"]:
        out.append(f"<li><b class='{'PASS' if c['pass'] else 'FAIL'}'>{'PASS' if c['pass'] else 'FAIL'}</b> hard: {esc(c['check'])} — {esc(c['detail'])}</li>")
    for c in v.get("criteria", []):
        out.append(f"<li><b class='{'PASS' if c['pass'] else 'FAIL'}'>{'PASS' if c['pass'] else 'FAIL'}</b> {esc(c['criterion'])} — <i>{esc(c.get('evidence', ''))}</i></li>")
    if v and not v.get("scenario_happened", True):
        out.append(f"<li><b class='VOID'>VOID</b> scenario did not happen: {esc(v.get('scenario_evidence', ''))}</li>")
    out.append("</ul></details>")
    return "".join(out)


def write_html(summary, path, title):
    avs = sorted({k[0] for k in summary})
    cases = sorted({k[1] for k in summary})
    rows = []
    for c in cases:
        cells = []
        for av in avs:
            st, rs = summary.get((av, c), ("-", []))
            valid = [r for r in rs if r["status"] in ("PASS", "FAIL")]
            cells.append(f"<td><span class='b {st}'>{st}</span> {sum(r['status']=='PASS' for r in valid)}/{len(valid)}</td>")
        rows.append(f"<tr><td><a href='#{esc(c)}'>{esc(c)}</a></td>{''.join(cells)}</tr>")
    body = [f"<h1>{esc(title)}</h1><table><tr><th>case</th>{''.join(f'<th>{esc(a)}</th>' for a in avs)}</tr>{''.join(rows)}</table>",
            "<p style='color:var(--mut)'>Text-mode run: timestamps are turn numbers (T#); highlighted turns are the judge's evidence. "
            "FAIL = any hard-check failure, or judge failures in ≥2 of ≥3 valid runs (≥1 if fewer runs). VOID = the customer never triggered the scenario.</p>"]
    for c in cases:
        for av in avs:
            if (av, c) not in summary:
                continue
            st, rs = summary[(av, c)]
            case = rs[0]["case"]
            fixes = {x["verdict"].get("suggested_prompt_fix", "") for x in rs if x["verdict"]} - {""}
            body.append(f"<h2 id='{esc(c)}'>{esc(c)} · {esc(av)} <span class='b {st}'>{st}</span></h2>"
                        f"<p>{esc(case.get('title', ''))} <span style='color:var(--mut)'>(source: {esc(case.get('source', 'n/a'))})</span></p>")
            body += [render_run(r) for r in rs]
            body += [f"<div class='fix'><b>Possible fix (hypothesis, verify by re-running):</b> {esc(f)}</div>" for f in fixes]
    path.write_text(f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                    f"<title>{esc(title)}</title><style>{CSS}</style></head><body>{''.join(body)}"
                    "<script>document.querySelectorAll('[data-t]').forEach(e=>e.onclick=()=>{const a=e.closest('details').querySelector('audio');if(a){a.currentTime=+e.dataset.t;a.play()}})</script>"
                    "</body></html>")
