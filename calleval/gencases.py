"""`calleval gen-cases`: write test cases from the agent's own prompt and tools, using the configured language model."""
import json, re
from .core import ROOT, load_config
from .llm import chat
from . import ui

SCHEMA = """Each case is a JSON object:
{"id": "kebab-case-id", "title": "one line", "persona": "name, age/mood, speaking style",
 "goal": "what the customer wants on this call (concrete: dates, times, names)",
 "quirks": ["what the customer does or says, and when (a trap: wrong info, interruption, ambiguity, pressure, language switch...)"],
 "precondition": "what the CUSTOMER must have done for the test to count",
 "criteria": ["yes/no statement about what the AGENT did, checkable from the transcript"],
 "mock_overrides": {"<tool_name>": {"error": "..."}}   // optional: force a tool to fail or return something odd
}"""


def ask_model(cfg, agent, n, existing):
    tools = "\n".join(f"- {t['function']['name']}: {t['function'].get('description', '')[:160]}" for t in agent["tools"]) or "(none)"
    system = ("You design test cases for a phone voice agent. Read its prompt and write cases that each target ONE promise, rule, tool, constraint, "
              "handoff or language behaviour stated in the prompt, plus realistic traps a real caller creates. Output ONLY a JSON array, no prose.")
    user = (f"AGENT PROMPT:\n{agent['prompt'][:14000]}\n\nTOOLS:\n{tools}\n\nExisting test ids (do not repeat these topics): {', '.join(existing)}\n\n"
            f"Write {n} NEW cases.\n{SCHEMA}\nRules: criteria must be about the agent's behaviour; no case may need information the prompt does not provide; "
            "persona speech must be plausible on a phone line.")
    llm = {**cfg["judge_llm"], "max_tokens": 4000, "temperature": 0.5}
    msg, _ = chat(llm, [{"role": "system", "content": system}, {"role": "user", "content": user}])
    m = re.search(r"\[.*\]", msg.get("content") or "", re.S)
    return json.loads(m.group(0)) if m else []


def clean(c, i):
    need = ("persona", "goal", "precondition", "criteria")
    if not all(c.get(k) for k in need) or not isinstance(c["criteria"], list):
        return None
    cid = re.sub(r"[^a-z0-9]+", "-", str(c.get("id") or c.get("title") or f"case-{i}").lower()).strip("-")[:50]
    out = {"id": cid, "title": c.get("title", cid), "source": "generated from the agent's prompt", "persona": c["persona"], "goal": c["goal"],
           "quirks": c.get("quirks") if isinstance(c.get("quirks"), list) else [], "precondition": c["precondition"],
           "criteria": [str(x) for x in c["criteria"]], "split": "heldout" if i % 3 == 2 else "train"}
    if isinstance(c.get("mock_overrides"), dict) and c["mock_overrides"]:
        out["mock_overrides"] = c["mock_overrides"]
    return out


def run(agent, n):
    cfg = load_config()
    existing = [json.loads(p.read_text()) for p in (ROOT / "cases" / "universal").glob("*.json")]
    existing = [c["id"] for d in existing for c in (d if isinstance(d, list) else [d])]
    ui.step(f"reading the prompt ({len(agent['prompt']):,} characters) and {len(agent['tools'])} tool(s)")
    cases, raw = [], []
    for attempt in (1, 2):
        ui.step(f"asking {cfg['judge_llm']['model']} to write {n} test cases" + (" (retry: the first answer was not valid)" if attempt == 2 else " (this can take a minute)"))
        try:
            raw = ask_model(cfg, agent, n, existing)
        except json.JSONDecodeError:
            raw = []
        cases = [x for x in (clean(c, i) for i, c in enumerate(raw)) if x]
        if cases:
            break
    if not cases:
        return None
    ui.step(f"checking each case has a goal, a precondition and criteria: {len(cases)} of {len(raw)} kept")
    d = ROOT / "cases" / "generated" / agent["name"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "generated.json").write_text(json.dumps(cases, indent=2, ensure_ascii=False))
    for c in cases:
        ui.line("✓", "green", f"{c['id']:36} {c['split']:8}", c["title"][:70])
    return d / "generated.json"
