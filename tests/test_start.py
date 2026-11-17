"""No-key check of `calleval start`: fake models drive the whole guided flow (setup check, run, LLM judge, results, report)."""
import json, os, shutil, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from calleval import cli, core, llm, start

def persona(msgs, tools):
    n = sum(1 for m in msgs if m["role"] == "assistant")
    return {"content": ["I want to book tomorrow at 10 AM", "yes please, Anita Rao [END]"][min(n, 1)]}
def agent(msgs, tools):
    last = msgs[-1]
    if last["role"] == "user" and "10 AM" in last["content"]:           # call the booking tool with the right format
        return {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "book_appointment", "arguments": json.dumps({
            "patient_name": "Anita Rao", "patient_phone": "1", "branch_name": "Indiranagar", "practitioner_name": "Dr. Rajendra Prasad", "start_time": "2026-11-18 10:00:00"})}}]}
    return {"content": "Booked for ten AM tomorrow."}
def judge(msgs, tools):
    text = msgs[-1]["content"]
    bad = "tool-failure-honesty" in text.split("\n")[0]
    return {"content": json.dumps({"scenario_happened": True, "scenario_evidence": "T1: ok", "suggested_prompt_fix": "say there was a problem" if bad else "",
            "criteria": [{"criterion": "The agent was honest", "pass": not bad, "evidence": "T2: Booked for ten AM tomorrow."}]})}
llm.FAKES.update(persona=persona, agent=agent, judge=judge)
os.environ["FAKEKEY"] = "1"
mk = lambda n: {"base_url": f"fake:{n}", "key_env": "FAKEKEY", "model": n}
cfg = lambda: {**core.DEFAULTS, "agent_llm": mk("agent"), "persona_llm": mk("persona"), "judge_llm": mk("judge"), "turns": 3, "runs": 1}
root = Path(tempfile.mkdtemp())
core.load_config = cli.load_config = start.load_config = cfg
core.ROOT = cli.ROOT = start.ROOT = root
shutil.copytree(Path(__file__).resolve().parent.parent / "agents", root / "agents")
shutil.copytree(Path(__file__).resolve().parent.parent / "cases", root / "cases")
(root / "templates").mkdir()

cli.main(["start", "--agent", "maya", "--version", "v2", "--cases", "relative-date-resolution,tool-failure-honesty", "--yes", "--no-open", "--run-id", "s1"])
d = root / "runs/s1/maya-v2"
assert (d / "relative-date-resolution/1/verdict.json").exists() and (d / "tool-failure-honesty/1/verdict.json").exists()
assert (root / "runs/s1/report.html").stat().st_size > 1000
from calleval.report import load_runs, summarize
s = summarize(load_runs(root / "runs/s1"))
assert s[("maya-v2", "relative-date-resolution")][0] == "PASS" and s[("maya-v2", "tool-failure-honesty")][0] == "FAIL", s
# a stub agent is refused before spending anything
try:
    cli.main(["start", "--agent", "nope", "--yes"])
except SystemExit as e:
    assert e.code == 2
print("OK")
