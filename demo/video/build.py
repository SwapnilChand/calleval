"""Builds the demo film's scenes from REAL captured material (terminal text in assets/term, report screenshots, call audio,
and the v2-vs-v3 comparison read from runs/imp). Run: python3 build.py && npx hyperframes check && npx hyperframes render"""
import html, json, math, re, sys
from pathlib import Path
HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

FONT_UI, FONT_MONO = "Inter, system-ui, sans-serif", "'JetBrains Mono', monospace"
CSS_BASE = """
#root{position:absolute;inset:0;background:#0b0d12;color:#f2f4f8;font-family:%s;overflow:hidden}
.mono{font-family:%s}.dim{color:#a3abc0}.g{color:#3ddc97}.r{color:#ff6b6b}.a{color:#f5b942}.c{color:#6ec1ff}.b{font-weight:700}
""" % (FONT_UI, FONT_MONO)


def scene(sid, body, script, extra_css="", dur=10):
    return f"""<template>
  <style>{CSS_BASE}{extra_css}</style>
  <div id="root" data-composition-id="{sid}" data-width="1920" data-height="1080">{body}</div>
  <script>
    const tl = gsap.timeline({{ paused: true }});
    {script}
    window.__timelines["{sid}"] = tl;
  </script>
</template>
"""


# ---------------------------------------------------------------- terminal helper
CPL, LH = 96, 41          # chars per wrapped line at 26px mono in a 1700px window; line height px


def colour(line):
    s = line.strip()
    if s.startswith("✓"): return "g"
    if s.startswith("✗"): return "r"
    if s.startswith("!"): return "a"
    if s.startswith("…"): return "dim"
    if s.startswith("next:"): return "dim"
    if s.startswith("calleval") or s.startswith("maya"): return "c b"
    return ""


def terminal(sid, blocks, dur, title="terminal", view_h=700):
    """blocks: [{'t': start, 'cmd': str, 'out': [lines], 'gap': 0.14, 'cls': optional fn}] -> html+js. Real text only."""
    html_lines, js, y, rows = [], [], 0, 0
    for bi, b in enumerate(blocks):
        cmd_id = f"{sid}-c{bi}"
        html_lines.append(f'<div class="ln mono" id="{cmd_id}"><span class="dim">$ </span><span id="{cmd_id}-t"></span></div>')
        top = y
        y += LH * max(1, math.ceil((len(b["cmd"]) + 2) / CPL))
        t0 = b["t"]
        typ = max(0.5, len(b["cmd"]) * 0.028)
        js.append(f'tl.fromTo("#{cmd_id}",{{opacity:0}},{{opacity:1,duration:0.05}},{t0});'
                  f'const o{bi}={{n:0}};tl.to(o{bi},{{n:{len(b["cmd"])},duration:{typ:.2f},ease:"none",onUpdate:()=>{{document.getElementById("{cmd_id}-t").textContent={json.dumps(b["cmd"])}.slice(0,Math.round(o{bi}.n))}}}},{t0 + 0.05});')
        t = t0 + typ + 0.35
        for li, line in enumerate(b["out"]):
            lid = f"{sid}-o{bi}-{li}"
            cls = (b.get("cls") or colour)(line)
            html_lines.append(f'<div class="ln mono {cls}" id="{lid}">{html.escape(line) if line.strip() else "&nbsp;"}</div>')
            js.append(f'tl.fromTo("#{lid}",{{opacity:0}},{{opacity:1,duration:0.06}},{t:.2f});')
            y += LH * max(1, math.ceil(max(1, len(line)) / CPL))
            t += b.get("gap", 0.14)
        y += 14
        scroll = max(0, y - view_h)
        js.append(f'tl.to("#{sid}-scroll",{{y:{-scroll},duration:0.5,ease:"power2.out"}},{t0 + typ + 0.2:.2f});' if bi else "")
        # keep last output in view as it grows: second scroll at block end
        js.append(f'tl.to("#{sid}-scroll",{{y:{-scroll},duration:0.6,ease:"power2.out"}},{t - 0.1:.2f});')
    css = f"""
#{sid}-term{{position:absolute;left:110px;top:110px;width:1700px;height:860px;background:#10141c;border-radius:20px;border:1px solid #26324a;overflow:hidden}}
#{sid}-bar{{position:absolute;left:0;right:0;top:0;height:58px;background:#171d29;border-bottom:1px solid #26324a}}
#{sid}-bar i{{position:absolute;top:21px;width:16px;height:16px;border-radius:8px}}
#{sid}-bar span{{position:absolute;left:0;right:0;top:15px;text-align:center;font-size:28px;color:#a3abc0}}
#{sid}-view{{position:absolute;left:0;right:0;top:58px;bottom:0;overflow:hidden}}
#{sid}-scroll{{position:absolute;left:36px;right:36px;top:30px}}
.ln{{font-size:28px;line-height:{LH}px;white-space:pre-wrap;word-break:break-word}}
"""
    body = (f'<div id="{sid}-term"><div id="{sid}-bar"><i style="left:26px;background:#ff5f56"></i><i style="left:54px;background:#ffbd2e"></i>'
            f'<i style="left:82px;background:#27c93f"></i><span>{html.escape(title)}</span></div>'
            f'<div id="{sid}-view"><div id="{sid}-scroll" data-layout-allow-overflow>{"".join(html_lines)}</div></div></div>')
    return body, "\n    ".join(x for x in js if x), css


def lines(name):
    return [l.rstrip("\n") for l in (HERE / "assets" / "term" / name).read_text().splitlines()]


def nonempty(ls):
    return [l for l in ls if l.strip()]


# ---------------------------------------------------------------- scene 1: hook
s1 = scene("hook", """
<div id="h1" style="position:absolute;left:160px;top:300px;width:1700px;font-size:88px;font-weight:700;letter-spacing:-0.03em;line-height:1.08;white-space:nowrap">Your voice agent passed every text test.</div>
<div id="h2" style="position:absolute;left:160px;top:560px;width:1700px;font-size:88px;font-weight:700;letter-spacing:-0.03em;line-height:1.08;color:#ff6b6b;white-space:nowrap">Then a caller said their name.</div>
""", """
tl.set("#h1",{opacity:1},0);
tl.fromTo("#h2",{opacity:0,y:30},{opacity:1,y:0,duration:0.5,ease:"power3.out"},2.5);
tl.to("#h1",{opacity:0.35,duration:0.4},2.5);""")

# ---------------------------------------------------------------- scene 2: the real call
BUB = """
.win{position:absolute;left:210px;top:90px;width:1500px;height:900px;background:#10141c;border:1px solid #26324a;border-radius:22px;overflow:hidden}
.top{position:absolute;left:0;right:0;top:0;height:84px;background:#171d29;border-bottom:1px solid #26324a;font-size:30px;line-height:84px;padding-left:36px}
.top b{color:#3ddc97}.rec{position:absolute;right:36px;top:0;font-size:30px;color:#ff6b6b}
.bub{position:absolute;max-width:900px;font-size:36px;line-height:1.3;padding:22px 30px;border-radius:26px}
.ag{left:36px;background:#1d2535;border:1px solid #2b3855;border-bottom-left-radius:6px}
.cu{right:36px;background:#1e4a8a;border-bottom-right-radius:6px}
.who{display:block;font-size:28px;color:#a3abc0;margin-bottom:6px}
.chip{position:absolute;font-size:30px;padding:16px 26px;border-radius:14px;background:#2a1618;border:2px solid #ff6b6b;color:#ff9a9a;line-height:1.3}
.cap{position:absolute;left:0;right:0;bottom:46px;text-align:center;font-size:44px;font-weight:700}
"""
s2 = scene("call", """
<div class="win">
  <div class="top"><b>●</b> Real audio call &nbsp;·&nbsp; agent under test ⇄ simulated customer <span class="rec">recorded locally</span></div>
  <div style="position:absolute;left:0;top:84px;height:6px;width:1500px;background:#1d2535"><div id="prog" style="height:6px;width:0;background:#3ddc97"></div></div>
  <div id="a1" class="bub ag" style="top:130px"><span class="who">Maya (agent)</span>Could you please confirm your full name for the booking?</div>
  <div id="c1" class="bub cu" style="top:310px"><span class="who">Customer</span>Neha Kapoor.</div>
  <div id="stt" class="chip" style="left:36px;top:480px"><span class="who" style="color:#ff9a9a">what the agent's speech-to-text wrote</span>“Ne Kippur.”</div>
  <div id="tool" class="chip mono" style="right:36px;top:480px;font-size:28px">book_appointment(<br>&nbsp;&nbsp;patient_name = “Ne Kippur”)</div>
  <div id="a2" class="bub ag" style="top:660px"><span class="who">Maya (agent)</span>Your appointment is successfully booked.</div>
  <div id="cap" class="cap" style="color:#ff6b6b">Booked under the wrong name. The agent never read it back.</div>
</div>""", """
tl.fromTo("#a1",{opacity:0,y:24},{opacity:1,y:0,duration:0.35,ease:"power3.out"},0.6);
tl.fromTo("#c1",{opacity:0,y:24},{opacity:1,y:0,duration:0.35,ease:"power3.out"},5.0);
tl.fromTo("#stt",{opacity:0,scale:0.92},{opacity:1,scale:1,duration:0.3,ease:"back.out(2)"},6.4);
tl.fromTo("#tool",{opacity:0,scale:0.92},{opacity:1,scale:1,duration:0.3,ease:"back.out(2)"},7.0);
tl.fromTo("#a2",{opacity:0,y:24},{opacity:1,y:0,duration:0.35,ease:"power3.out"},7.4);
tl.fromTo("#prog",{width:0},{width:1500,duration:11.3,ease:"none"},0.5);
tl.fromTo("#stt",{boxShadow:"0 0 0 0 rgba(255,107,107,0)"},{boxShadow:"0 0 40px 6px rgba(255,107,107,0.55)",duration:0.8,yoyo:true,repeat:3,ease:"sine.inOut"},12.4);
tl.fromTo("#tool",{boxShadow:"0 0 0 0 rgba(255,107,107,0)"},{boxShadow:"0 0 40px 6px rgba(255,107,107,0.55)",duration:0.8,yoyo:true,repeat:3,ease:"sine.inOut"},12.4);
tl.fromTo("#cap",{opacity:0,y:20},{opacity:1,y:0,duration:0.4,ease:"power3.out"},11.8);""", BUB)

# ---------------------------------------------------------------- scene 3: product in the terminal
voice_out = [l for l in nonempty(lines("voicerun.txt")) if not l.strip().startswith("next:") and len(l) < 100][:4]
b3, j3, c3 = terminal("prod", [
    {"t": 0.3, "cmd": "calleval new-agent clinic --livekit-file agent.py", "out": [l for l in nonempty(lines("newagent.txt")) if len(l) < 100 and not l.strip().startswith("next:")], "gap": 0.2},
    {"t": 3.9, "cmd": "calleval gen-cases --agent clinic", "out": [l for l in nonempty(lines("gencases.txt")) if len(l) < 100 and not l.strip().startswith(("next:", "✓ wrote"))], "gap": 0.2},
    {"t": 7.7, "cmd": "calleval voice-run --agent maya --split train", "out": voice_out, "gap": 0.3},
], 14, "calleval")
j3 += '\n    tl.fromTo("#prod-o2-%d",{color:"#3ddc97"},{color:"#ffffff",duration:0.9,yoyo:true,repeat:3,ease:"sine.inOut"},10.4);' % (len(voice_out) - 1)
s3 = scene("product", b3, j3, c3)

# ---------------------------------------------------------------- scene 4: the report (real screenshots)
s4 = scene("report", """
<img id="rt" src="assets/report_table.png" style="position:absolute;left:210px;top:120px;width:1500px;height:819px;border-radius:14px;border:1px solid #26324a"/>
<div id="rt-cap" style="position:absolute;left:0;right:0;top:960px;text-align:center;font-size:48px;font-weight:700"><span class="g">6 pass</span> <span class="dim">·</span> <span class="r">4 fail</span> <span class="dim">·</span> <span class="dim">1 inconclusive</span></div>
<img id="rv" src="assets/report_verdict.png" style="position:absolute;left:210px;top:330px;width:1500px;height:383px;border-radius:14px;border:1px solid #26324a"/>
<div id="rv-a" style="position:absolute;left:0;right:0;top:170px;text-align:center;font-size:56px;font-weight:700">Every failure comes with the <span class="r">quoted evidence</span></div>
<div id="rv-b" style="position:absolute;left:0;right:0;top:790px;text-align:center;font-size:56px;font-weight:700">and a <span class="a">suggested fix</span></div>
""", """
tl.fromTo("#rt",{opacity:0,y:40},{opacity:1,y:0,duration:0.5,ease:"power3.out"},0.3);
tl.fromTo("#rt-cap",{opacity:0},{opacity:1,duration:0.4},1.4);
tl.to("#rt",{opacity:0,y:-30,duration:0.35,ease:"power2.in"},4.6);
tl.to("#rt-cap",{opacity:0,duration:0.3},4.5);
tl.fromTo("#rv",{opacity:0,y:40},{opacity:1,y:0,duration:0.5,ease:"power3.out"},5.0);
tl.fromTo("#rv-a",{opacity:0,y:20},{opacity:1,y:0,duration:0.4},5.3);
tl.fromTo("#rv-b",{opacity:0,y:20},{opacity:1,y:0,duration:0.4},7.4);
tl.set("#rv",{opacity:0},-1);""")

# ---------------------------------------------------------------- scene 5: improve (real output, real diff, real comparison)
import subprocess
def short(l, n=104):
    return l if len(l) <= n else l[: n - 1].rstrip() + "…"
_changes = (ROOT / "agents/maya/v3/CHANGES.md").read_text().split("## Changes\n")[1].split("\n\n")[0].strip().splitlines()
imp_out = [l for l in nonempty(lines("improve.txt")) if not l.strip().startswith(("…", "-"))] + ["    " + c.strip() for c in _changes[:3]]
diff = subprocess.run(["diff", str(ROOT / "agents/maya/v2/prompt.md"), str(ROOT / "agents/maya/v3/prompt.md")], capture_output=True, text=True).stdout.splitlines()
added = [l[2:].replace("**", "") for l in diff if l.startswith("> ")]
import difflib
old_lines = [l[2:] for l in diff if l.startswith("< ")]
def inserted(new):
    """Only the words the new line adds relative to its closest old line (so the key phrase is what is shown)."""
    best = max(old_lines, key=lambda o: difflib.SequenceMatcher(None, o, new).ratio(), default="")
    ow, nw = best.split(), new.split()
    ins = [" ".join(nw[j1:j2]) for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ow, nw).get_opcodes() if tag in ("insert", "replace")]
    return " ".join(ins)
diff_out = []
for l in added:
    if "read it back" in l:
        diff_out.append("+ …" + inserted(l).strip())
    elif "retry the booking call" in l:
        diff_out.append("+ " + l.strip().lstrip("- ")[:200])
diff_out = diff_out[:2]
b5, j5, c5 = terminal("imp", [
    {"t": 0.3, "cmd": "calleval improve --agent maya --from vcmp", "out": imp_out, "gap": 0.22},
    {"t": 3.3, "cmd": "diff agents/maya/v2/prompt.md agents/maya/v3/prompt.md", "out": diff_out, "gap": 1.5, "cls": lambda l: "g"},
], 15, "calleval")

def comparison():
    from calleval.report import load_runs
    st = {}
    for r in load_runs(ROOT / "runs" / "imp2"):
        if r["status"] in ("PASS", "FAIL", "INCONCLUSIVE", "VOID"):
            st[(r["version"], r["case"]["id"])] = r["status"]
    return [(c, st[("v2", c)], st[("v3", c)]) for c in sorted({c for v, c in st if v == "v3"}) if ("v2", c) in st]

card = ""; cardjs = ""
rows = comparison() if (ROOT / "runs" / "imp2" / "maya-v3").exists() else []
if rows:
    cl = {"PASS": "g", "FAIL": "r"}
    def row(c, a, b):
        return (f'<div class="rw"><span class="lb">{html.escape(c)}</span><span class="{cl.get(a, "dim")} b">{a.lower()}</span>'
                f'<span class="ar">→</span><span class="{cl.get(b, "dim")} b">{b.lower()}</span></div>')
    card = ('<div id="card"><div class="ct">Re-run on the same cases · same model · 1 run each</div>'
            '<div class="rw hd"><span class="lb"></span><span>v2</span><span class="ar"></span><span>v3</span></div>'
            + "".join(row(*r) for r in rows)
            + '<div class="fx">No change yet on these cases. <span class="a b">improve proposes, re-runs verify.</span></div></div>')
    cardjs = ('tl.to("#imp-term",{opacity:0,duration:0.4},11.4);'
              'tl.fromTo("#card",{opacity:0,y:30},{opacity:1,y:0,duration:0.5,ease:"power3.out"},11.8);')
card_css = """
#card{position:absolute;left:260px;top:210px;width:1400px;height:660px;background:#10141c;border:1px solid #26324a;border-radius:24px;padding:48px 64px;opacity:0}
.ct{font-size:34px;color:#a3abc0;margin-bottom:36px}
.rw{display:flex;gap:40px;align-items:baseline;font-size:46px;margin-bottom:26px}.rw .lb{width:760px;font-size:40px;color:#e6e9f2}.rw .ar{color:#a3abc0}.rw.hd{font-size:34px;color:#a3abc0}
.fx{font-size:36px;line-height:1.4;margin-top:16px}
"""
s5 = scene("improve", b5 + card, j5 + "\n    " + cardjs, c5 + card_css)

# ---------------------------------------------------------------- scene 6: end card
s6 = scene("end", """
<div id="e1" style="position:absolute;left:0;right:0;top:300px;text-align:center;font-size:150px;font-weight:700;letter-spacing:-0.04em">calleval</div>
<div id="e2" style="position:absolute;left:0;right:0;top:500px;text-align:center;font-size:52px;color:#a3abc0">Test your voice agent before your customers do.</div>
<div id="e3" class="mono" style="position:absolute;left:0;right:0;top:640px;text-align:center;font-size:44px;color:#3ddc97">github.com/SwapnilChand/calleval</div>
<div id="e4" style="position:absolute;left:0;right:0;top:730px;text-align:center;font-size:34px;color:#a3abc0">open source · MIT · runs on your machine · keys optional</div>
""", """
tl.set("#e1",{opacity:1},0);
tl.fromTo("#e2",{opacity:0,y:16},{opacity:1,y:0,duration:0.45,ease:"power3.out"},0.6);
tl.fromTo("#e3",{opacity:0,y:16},{opacity:1,y:0,duration:0.45,ease:"power3.out"},1.4);
tl.fromTo("#e4",{opacity:0,y:16},{opacity:1,y:0,duration:0.45,ease:"power3.out"},2.1);
tl.to("#e1",{scale:1.04,duration:3.5,ease:"sine.inOut"},0.5);""")

(HERE / "compositions").mkdir(exist_ok=True)
for name, content in (("hook", s1), ("call", s2), ("product", s3), ("report", s4), ("improve", s5), ("end", s6)):
    (HERE / "compositions" / f"{name}.html").write_text(content)
print("scenes written")
