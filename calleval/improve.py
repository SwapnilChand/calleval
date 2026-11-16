"""`calleval improve`: from the failed train-split cases of a run, propose a revised prompt as a new version (never reads held-out cases)."""
import difflib, json, re, shutil
from pathlib import Path
from .core import ROOT, versions, load_config
from .llm import chat
from .report import load_runs
from . import ui

SYSTEM = ("You improve the system prompt of a phone voice agent. You get the current prompt and a list of failed test cases with evidence. "
          "Make the SMALLEST edits that fix the failures. Put each fix in the section of the prompt where it belongs (a tool rule next to the other tool rules, "
          "a spoken-format rule next to the other speaking rules); do not append loose rules at the end. Keep everything else exactly as it is. "
          "Do not add rules about anything not shown in the failures. Output exactly:\n=== CHANGES ===\n- <fix>: <why>\n(one line per change)\n=== PROMPT ===\n<the complete new prompt>")


def failures(base, agent, version):
    out = []
    for r in load_runs(base):
        if f"{r['agent']}-{r['version']}" != f"{agent}-{version}" or r["case"].get("split", "train") == "heldout":
            continue                                   # held-out cases stay unseen
        hard = [c for c in r["checks"] if not c["pass"]]
        v = r.get("verdict") or {}
        crit = [c for c in v.get("criteria", []) if not c.get("pass")] if v.get("scenario_happened", True) else []
        if r["status"] == "FAIL" or hard:
            out.append({"case": r["case"]["id"], "goal": r["case"]["goal"], "hard": hard, "criteria": crit, "fix": v.get("suggested_prompt_fix", "")})
    return out


def describe(f):
    lines = [f"CASE {f['case']} (customer goal: {f['goal'][:150]})"]
    lines += [f"  hard check failed: {h['check']} — {h['detail'][:200]}" for h in f["hard"]]
    lines += [f"  criterion failed: {c['criterion']} — evidence: {c.get('evidence', '')[:240]}" for c in f["criteria"]]
    if f["fix"]:
        lines.append(f"  judge's suggested fix (a hypothesis): {f['fix'][:300]}")
    return "\n".join(lines)


def run(agent, version, from_run, model_note=True):
    base = ROOT / "runs" / from_run
    cfg = load_config()
    fails = failures(base, agent, version)
    if not fails:
        return None
    src = ROOT / "agents" / agent / version
    ui.step(f"{len(fails)} failed train case(s) in {from_run}: {', '.join(f['case'] for f in fails)} (held-out cases are not read)")
    old = (src / "prompt.md").read_text()
    ui.step(f"asking {cfg['judge_llm']['model']} for the smallest prompt edits that fix them (this can take a minute or two)")
    llm = {**cfg["judge_llm"], "max_tokens": 9000, "temperature": 0.2}
    msg, _ = chat(llm, [{"role": "system", "content": SYSTEM},
                        {"role": "user", "content": f"CURRENT PROMPT:\n{old}\n\nFAILURES:\n" + "\n\n".join(describe(f) for f in fails)}])
    text = msg.get("content") or ""
    m = re.search(r"=== CHANGES ===\s*(.*?)\s*=== PROMPT ===\s*(.*)\Z", text, re.S)
    if not m or len(m.group(2)) < 0.5 * len(old):
        return "bad"
    changes, new = m.group(1).strip(), m.group(2).strip() + "\n"
    n = versions(agent)[-1]
    dst = ROOT / "agents" / agent / f"v{n + 1}"
    shutil.copytree(ROOT / "agents" / agent / f"v{n}", dst)
    (dst / "prompt.md").write_text(new)
    (dst / "CHANGES.md").write_text(f"# v{n + 1}: proposed from failures in run '{from_run}' on {version}\n\n## Targeted failures\n"
                                    + "\n".join(f"- {f['case']}" for f in fails) + f"\n\n## Changes\n{changes}\n\n(A hypothesis until re-run: check train and held-out results.)\n")
    d = list(difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0))
    add, rem = sum(1 for x in d if x.startswith("+") and not x.startswith("+++")), sum(1 for x in d if x.startswith("-") and not x.startswith("---"))
    ui.line("✓", "green", f"created agents/{agent}/v{n + 1}/prompt.md", f"+{add} −{rem} lines vs {version}")
    for line in changes.splitlines()[:8]:
        print(f"    {line[:150]}")
    return n + 1
