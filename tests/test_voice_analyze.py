"""No-key unit check of the voice detectors with a synthetic call: latency, cut-off, repeat, STT swap."""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calleval.voice.analyze import analyze, norm

assert norm("10 AM") == norm("10 a.m.") == ["10am"]
d = Path(tempfile.mkdtemp())
ev = [{"t": 1, "role": "twin", "kind": "user_state", "new": "speaking"}, {"t": 3, "role": "twin", "kind": "user_state", "new": "listening"},
      {"t": 9, "role": "twin", "kind": "agent_state", "new": "speaking"}, {"t": 12, "role": "twin", "kind": "agent_state", "new": "listening"}]
(d / "events-twin.jsonl").write_text("\n".join(json.dumps(e) for e in ev))
agent_t = "Your appointment is booked for tomorrow at ten with Doctor Prasad at Indiranagar."
tr = {"turns": [{"i": 0, "role": "customer", "text": "Book me with Dr Prasad at Indiranagar", "t": 1},
                {"i": 1, "role": "agent", "text": agent_t, "t": 9, "interrupted": True},
                {"i": 2, "role": "agent", "text": agent_t, "t": 20}],
      "tool_calls": [], "heard": [{"by": "agent", "t": 3, "text": "Book me with Dr Prasad at Indurnagar"}]}
(d / "transcript.json").write_text(json.dumps(tr))
a = analyze(d, 0)
kinds = {f["type"] for f in a["flags"]}
assert a["latency_s"] == [6.0] and {"slow_response", "agent_cut_off", "repeat"} <= kinds, (a["latency_s"], kinds)
assert a["stt_mismatches"][0]["word_swaps"] == [["indiranagar", "indurnagar"]] or a["stt_mismatches"][0]["word_swaps"] == [("indiranagar", "indurnagar")]
print("OK")
