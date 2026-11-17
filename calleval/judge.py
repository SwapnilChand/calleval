"""Hard checks (code) + judge input/verdict handling. The judge itself is Claude Code reading judge_input.md and
writing verdict.json (default, uses the subscription), or `judge --llm` which calls cfg['judge_llm'] (fallback)."""
import json, re
from .llm import chat

VERDICT_FORMAT = """Write verdict.json next to this file, exactly:
{"scenario_happened": true|false,
 "scenario_evidence": "T<n>: short quote proving the scenario/quirk actually occurred (or why not)",
 "criteria": [{"criterion": "<copied>", "pass": true|false, "evidence": "T<n>: exact short quote from the transcript"}],
 "suggested_prompt_fix": "<only if something failed: concrete edit to the agent's system prompt, else empty>"}
Rules: judge ONLY from the transcript and tool calls below. Every verdict needs a quote with its turn number; no quote = pass:false.
If the customer never did the scenario (precondition false), set scenario_happened:false and still fill criteria with pass:false.
Do not give credit for intent; the agent must have actually said/done it."""


def run_checks(checks, tool_log, turns=()):
    out = []
    for c in checks or []:
        if "agent_text_must_not_match" in c:                 # e.g. raw ISO dates spoken to a caller (TTS reads them badly)
            bad = [x for x in turns if x["role"] == "agent" and re.search(c["agent_text_must_not_match"], x["text"])]
            out.append({"check": f"agent never says /{c['agent_text_must_not_match']}/", "pass": not bad,
                        "detail": "clean" if not bad else "; ".join(f"T{x['i']}: {x['text'][:80]}" for x in bad)})
            continue
        calls = [x for x in tool_log if x["name"] == c["tool"]]
        hit = [x for x in calls if all(re.search(rx, str(x["args"].get(k, ""))) for k, rx in c.get("args", {}).items())]
        want = c.get("called", True)
        ok = bool(hit) if want else not (hit if c.get("args") else calls)   # not-called + args = no call MATCHING those args
        detail = (f"{len(hit)} matching call(s)" if want else f"{len(hit if c.get('args') else calls)} offending call(s), expected none")
        if want and calls and not hit:
            detail = f"called {len(calls)}x but args did not match {c.get('args')}; got {[x['args'] for x in calls]}"
        out.append({"check": f"{c['tool']} {'called' if want else 'NOT called'} {c.get('args', '')}".strip(),
                    "pass": ok, "detail": detail})
    return out


def render_transcript(t):
    lines = []
    for x in t["turns"]:
        lines.append(f"T{x['i']} {x['role'].upper()}" + (f" @{x['t']}s" if "t" in x else "") + f": {x['text']}" + ("   [CUT OFF by the other side]" if x.get("interrupted") else "")
                     + (f"   [tools: {', '.join(x['tools'])}]" if x.get("tools") else ""))
    tl = [f"T{x['turn']} {x['name']}({json.dumps(x['args'])}) -> {json.dumps(x['result'])}" for x in t["tool_calls"]]
    return "\n".join(lines), "\n".join(tl) or "(none)"


def voice_section(a):
    if not a:
        return ""
    L = ["## Voice analysis (automatic detectors on the audio/timing; hints with timestamps, not verdicts)",
         f"- response latency after caller stops (s): {a.get('latency_s')}; talk-over total: {a.get('talk_over_s')}s"]
    L += [f"- FLAG {f['type']}" + (f" T{f['turn']}" if "turn" in f else "") + (f" @{f['t']}s" if "t" in f else "") + f": {f['detail']}" for f in a.get("flags", [])]
    L += [f"- STT ({m['speaker']} turn T{m['turn']}): said '{m['said']}' / transcribed '{m['heard']}' swaps={m['word_swaps']}" for m in a.get("stt_mismatches", [])]
    if a.get("spoken_forms"):
        L.append("- how the agent's voice actually said numbers/dates (listening model, verbatim): " + a["spoken_forms"])
    return "\n".join(L) + "\n\n"


def platform_section(t):
    pl = t.get("platform")
    if not pl:
        return ""
    L = [f"## Provider record ({pl.get('provider')}): their own transcript of the same call, plus metrics. Tool calls are NOT visible in live runs; judge only from what was said.",
         f"- cost: {pl.get('cost')}, duration: {pl.get('duration')}s"]
    L += [f"- {x['role'].upper()}: {x['text'][:200]}" for x in pl.get("transcript", [])]
    lat = pl.get("latency") or {}
    if lat.get("time_to_first_audio") is not None:
        L.append(f"- provider latency: time_to_first_audio={lat.get('time_to_first_audio')}; interruptions={lat.get('interruption_stats')}")
    return "\n".join(L) + "\n\n"


def judge_input_md(t):
    c = t["case"]
    tr, tl = render_transcript(t)
    crit = "\n".join(f"{i+1}. {x}" for i, x in enumerate(c["criteria"]))
    return (f"# Judge: {c['id']} (run {t['run']}) agent {t['agent']} {t['version']}\n\n"
            f"## Scenario precondition (did the CUSTOMER actually do this?)\n{c.get('precondition', 'n/a')}\n\n"
            f"## Criteria (yes/no each)\n{crit}\n\n## Transcript\n{tr}\n\n## Tool calls\n{tl if not t.get('live') else '(not visible in a live run)'}\n\n{platform_section(t)}{voice_section(t.get('analysis'))}## Output\n{VERDICT_FORMAT}\n")


def llm_judge(cfg, t):
    msg, _ = chat(cfg["judge_llm"], [
        {"role": "system", "content": "You are a strict evaluator of voice-agent transcripts. Output only JSON."},
        {"role": "user", "content": judge_input_md(t)}])
    s = msg.get("content") or ""
    m = re.search(r"\{.*\}", s, re.S)
    return json.loads(m.group(0))
