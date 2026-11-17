"""No-key self-check: fake LLMs drive the real loop -> run -> checks -> verdict -> report. `python3 tests/test_loop.py`"""
import json, shutil, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from calleval import cli, core, llm
from calleval.judge import run_checks
from calleval.mocks import validate

# --- unit: checks + mock validation
log = [{"turn": 2, "name": "book", "args": {"start_time": "2026-11-18 10:00:00"}, "result": {}}]
assert run_checks([{"tool": "book", "called": True, "args": {"start_time": "^2026-11-18 10:00:00$"}}], log)[0]["pass"]
assert not run_checks([{"tool": "book", "called": True, "args": {"start_time": "^2026-11-19"}}], log)[0]["pass"]
assert not run_checks([{"tool": "book", "called": False}], log)[0]["pass"]
assert not run_checks([{"agent_text_must_not_match": r"\d{4}-\d{2}"}], [], [{"i": 1, "role": "agent", "text": "on 2026-11-18"}])[0]["pass"]
assert validate({"required": ["a"], "properties": {"a": {"enum": ["x"]}}}, {"a": "y"}, {}) == ["'a' must be one of ['x'], got 'y'"]
assert validate({"properties": {"t": {}}}, {"t": None}, {"t": r"^\d$"}) == []          # null is allowed (cancel has no new time)

# --- integration with fake agent + fake persona
state = {"n": 0}
def persona(msgs, tools):
    state["n"] += 1
    return {"content": ["I want to book tomorrow at 10 AM", "yes please, Anita Rao [END]"][min(state["n"] - 1, 1)]}
def agent(msgs, tools):
    last = msgs[-1]
    if last["role"] == "user" and "10 AM" in last["content"]:       # turn 1: call the tool with the right format
        return {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": "book_appointment", "arguments": json.dumps({"patient_name": "Anita Rao", "patient_phone": "1", "branch_name": "Indiranagar",
                                                                 "practitioner_name": "Dr. Rajendra Prasad", "start_time": "2026-11-18 10:00:00"})}}]}
    return {"content": "Booked for ten AM tomorrow."}
llm.FAKES.update(persona=persona, agent=agent)
fake = {"base_url": "fake:persona"}; fa = {"base_url": "fake:agent"}
core.load_config = cli.load_config = lambda: {**core.DEFAULTS, "persona_llm": fake, "agent_llm": fa, "turns": 4, "runs": 1}
core.ROOT = cli.ROOT = Path(tempfile.mkdtemp())
shutil.copytree(Path(__file__).resolve().parent.parent / "agents", core.ROOT / "agents")
shutil.copytree(Path(__file__).resolve().parent.parent / "cases", core.ROOT / "cases")
import calleval.report as rep
cli.main(["run", "--agent", "maya", "--version", "v1", "--cases", "relative-date-resolution,human-handoff", "--run-id", "t"])
d = core.ROOT / "runs/t/maya-v1"
t = json.loads((d / "relative-date-resolution/1/transcript.json").read_text())
assert t["ended"] == "customer_end" and t["tool_calls"][0]["result"]["status"] == "success", t
(d / "relative-date-resolution/1/verdict.json").write_text(json.dumps({"scenario_happened": True, "criteria": [
    {"criterion": "c", "pass": True, "evidence": "T3: Booked for ten AM"}]}))
cli.main(["report", "t"])
s = rep.summarize(rep.load_runs(core.ROOT / "runs/t"))
assert s[("maya-v1", "relative-date-resolution")][0] == "PASS", s
assert s[("maya-v1", "human-handoff")][0] == "UNJUDGED", s                       # no verdict yet
assert (core.ROOT / "runs/t/report.html").stat().st_size > 1000
ids = {c["id"] for c in core.load_cases("all")}                                   # English-only stack: Hindi case never loads
assert "language-switch-hindi" not in ids and "asks-name-never-invents" in ids and not core.load_cases("language-switch-hindi")
cfg = core.load_config(); hi = core.load_cases("language-switch-hindi", all_languages=True)[0]
assert core.why_not(core.load_agent("maya"), hi, cfg)                                                 # English-only stack: not suitable
cfg["languages"] = ["en", "hi"]
assert core.why_not(core.load_agent("maya"), hi, cfg) is None                                         # Hindi stack + prompt speaks Hindi
assert "does not claim" in core.why_not(core.load_agent("dental"), hi, cfg)                           # Hindi stack but the agent does not
print("OK")
