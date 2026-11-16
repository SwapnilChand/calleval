"""Detectors over one voice call (events + audio): latency, talk-over, cut-off turns, repeats, dead air, STT errors, spoken forms."""
import base64, difflib, json, re, urllib.request
from pathlib import Path

TH = {"slow_response_s": 3.0, "dead_air_s": 6.0, "repeat_ratio": 0.85}
NUM = re.compile(r"\d")


def norm(s):
    s = re.sub(r"[\u202f\u00a0]", " ", s.lower()).replace("a.m.", "am").replace("p.m.", "pm")
    s = re.sub(r"(\d)\s+(am|pm)\b", r"\1\2", s)
    return re.sub(r"[^a-z0-9 ]", " ", s).split()


def events(d):
    out = []
    for r in ("twin", "persona"):
        f = Path(d) / f"events-{r}.jsonl"
        if f.exists():
            out += [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
    return sorted(out, key=lambda e: e["t"])


def intervals(ev, role, kind, on):
    """[(start,end)] where state `kind` of `role` equals `on`."""
    res, start = [], None
    for e in ev:
        if e["role"] == role and e["kind"] == kind:
            if e["new"] == on and start is None:
                start = e["t"]
            elif e["new"] != on and start is not None:
                res.append((start, e["t"])); start = None
    return res


def analyze(d, t0):
    d = Path(d)
    tr = json.loads((d / "transcript.json").read_text()) if (d / "transcript.json").exists() else None
    ev = events(d)
    turns = tr["turns"] if tr else []
    flags = []
    rel = lambda t: round(t - t0, 2)
    # 1 response latency (twin's view: user stops speaking -> agent starts speaking)
    user = intervals(ev, "twin", "user_state", "speaking")
    agent = intervals(ev, "twin", "agent_state", "speaking")
    lat = []
    for (s, e_) in user:
        nxt = next((a for a in agent if a[0] >= e_), None)
        if nxt:
            lat.append(round(nxt[0] - e_, 2))
            if lat[-1] > TH["slow_response_s"]:
                flags.append({"type": "slow_response", "t": rel(e_), "detail": f"{lat[-1]}s from end of caller speech to agent speech"})
    # 2 talk-over: both speaking at once (twin's view)
    over = [(max(a[0], u[0]), min(a[1], u[1])) for a in agent for u in user if min(a[1], u[1]) > max(a[0], u[0]) + 0.25]
    for s, e_ in over:
        flags.append({"type": "talk_over", "t": rel(s), "detail": f"both sides speaking for {round(e_ - s, 1)}s"})
    # 3 cut-off agent turns
    for x in turns:
        if x["role"] == "agent" and x.get("interrupted"):
            flags.append({"type": "agent_cut_off", "turn": x["i"], "t": x["t"], "detail": f"agent turn interrupted: {x['text'][:70]}"})
    # 4 repetition (agent sentences repeated across turns)
    seen = []
    for x in turns:
        if x["role"] != "agent":
            continue
        for sent in re.split(r"(?<=[.?!])\s+", x["text"]):
            w = norm(sent)
            if len(w) < 6:
                continue
            for pt, pw in seen:
                if difflib.SequenceMatcher(None, w, pw).ratio() >= TH["repeat_ratio"]:
                    flags.append({"type": "repeat", "turn": x["i"], "detail": f"repeats an earlier agent sentence: {sent[:70]}"}); break
            seen.append((x["i"], w))
    # 5 dead air = nobody speaking for a long stretch; silent turns = tool ran, caller spoke again, agent never replied
    spans = sorted(user + agent)
    for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
        if s2 - max(e1, spans[0][1]) > TH["dead_air_s"] and s2 > e1:
            flags.append({"type": "dead_air", "t": rel(e1), "detail": f"{round(s2 - e1, 1)}s with nobody speaking"})
    if tr:
        for tc in tr["tool_calls"]:
            tt = tc.get("t")
            if tt is None or tc["name"] == "lookup_caller":
                continue
            nxt_agent = next((x["t"] for x in turns if x["role"] == "agent" and x["t"] > tt), None)
            nxt_cust = next((x["t"] for x in turns if x["role"] == "customer" and x["t"] > tt), None)
            if nxt_agent is None or (nxt_cust is not None and nxt_cust < nxt_agent):
                flags.append({"type": "no_reply_after_tool", "turn": tc["turn"], "detail": f"{tc['name']} ran but the agent gave no spoken reply before the caller's next turn"})
    # 6 STT: what the listener's speech-to-text wrote vs what the speaker was saying
    stt = []
    if tr:
        said = {"customer": [x for x in turns if x["role"] == "customer"], "agent": [x for x in turns if x["role"] == "agent"]}
        heard = {"customer": [h for h in tr.get("heard", []) if h["by"] == "agent"], "agent": [h for h in tr.get("heard", []) if h["by"] == "customer"]}
        for who in ("customer", "agent"):
            for h in heard[who]:
                best = max((x for x in said[who] if x["t"] <= h["t"]), key=lambda x: x["t"], default=None)   # latest turn by that speaker before it was transcribed
                if not best:
                    continue
                a, b = norm(best["text"]), norm(h["text"])
                diff = [(w1, w2) for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes() if tag == "replace" for w1, w2 in zip(a[i1:i2], b[j1:j2])]
                if diff:
                    stt.append({"speaker": who, "turn": best["i"], "said": best["text"][:90], "heard": h["text"][:90], "word_swaps": diff[:6]})
    return {"latency_s": lat, "talk_over_s": round(sum(e_ - s for s, e_ in over), 1), "flags": flags, "stt_mismatches": stt}


def spoken_forms(agent_wav, key, model="gemini-3.5-flash-lite"):
    """Listening model: verbatim words for the agent's audio (numbers as words). A hint, not a verdict."""
    a = base64.b64encode(Path(agent_wav).read_bytes()).decode()
    q = ("Transcribe this audio VERBATIM. Write every number, date, time and phone number exactly as it is spoken, in words "
         "(e.g. 'two zero two six'), never as digits. Output only the transcript.")
    body = {"contents": [{"parts": [{"text": q}, {"inlineData": {"mimeType": "audio/wav", "data": a}}]}]}
    r = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                               json.dumps(body).encode(), {"x-goog-api-key": key, "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=120))["candidates"][0]["content"]["parts"][0]["text"].strip()
