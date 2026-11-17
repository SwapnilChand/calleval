"""`calleval start`: one guided command. check -> agent -> cases -> run -> judge -> results -> report in the browser -> next step."""
import argparse, os, sys, time, webbrowser
from pathlib import Path
from . import ui
from .core import ROOT, Skip, config_path, date_vars, fill, load_agent, load_cases, load_config, versions

QUICK = ["relative-date-resolution", "wrong-date-then-correct", "tool-failure-honesty", "no-guessed-availability",
         "confirm-before-booking", "human-handoff", "asks-name-never-invents", "prompt-injection"]
TOTAL = 7


def stage(n, title, why=""):
    print(ui.c(f"\n [{n}/{TOTAL}] {title}", "bold", "cyan") + (ui.c(f"  {why}", "dim") if why else ""))


def applicable(agent, cases, cfg):
    cv = {**date_vars(cfg["now"]), **agent.get("case_vars", {})}
    out = []
    for c in cases:
        try:
            fill(c, cv)
            out.append(c)
        except Skip:
            pass
    return out


def pick_cases(agent, cfg, wanted):
    allc = load_cases("all", "all", agent["name"])
    if wanted:
        ids = wanted.split(",")
        return [c for c in allc if c["id"] in ids]
    ok = applicable(agent, allc, cfg)
    gen = [c for c in ok if "/generated/" in c["_file"]]
    quick = [c for c in ok if c["id"] in QUICK and c not in gen]
    quick.sort(key=lambda c: QUICK.index(c["id"]))
    return (quick[:6] + gen) if gen or quick else ok[:6]


def explain(run_id):
    """Failures in plain words, right in the terminal."""
    from .report import load_runs, summarize
    summ = summarize(load_runs(ROOT / "runs" / run_id))
    fails = [(k, rs) for k, (st, rs) in sorted(summ.items()) if st == "FAIL"]
    if not fails:
        print(ui.c("\n No failing cases in this run.", "green"))
        return fails
    print(ui.c(f"\n Why {len(fails)} case(s) failed:", "bold"))
    for (av, cid), rs in fails[:6]:
        r = next(x for x in rs if x["status"] == "FAIL")
        ui.line("✗", "red", cid)
        for h in [c for c in r["checks"] if not c["pass"]][:1]:
            print(ui.c(f"      check: {h['check']} ({h['detail'][:110]})", "dim"))
        for c in [c for c in (r.get("verdict") or {}).get("criteria", []) if not c.get("pass")][:2]:
            print(f"      {c['criterion'][:100]}\n      " + ui.c(f"“{c.get('evidence', '')[:150]}”", "dim"))
        fix = (r.get("verdict") or {}).get("suggested_prompt_fix")
        if fix:
            print("      " + ui.c("suggested fix: ", "yellow") + fix[:160])
    return fails


def run(a):
    from . import cli, gencases, setup
    t_all = time.time()
    cfg = load_config()
    ui.header("calleval start", "a guided run from setup to report", "Ctrl-C any time; runs resume")

    # 1 ---------------------------------------------------------------- setup
    stage(1, "Checking your setup", "which models will play the agent, the customer and the judge")
    rows, voice = setup.checks(cfg)
    bad = [r for r in rows if not r[1]]
    if config_path().exists() or not bad:
        for _, ok, d, fix in rows:
            print(f"  {ui.c('✓', 'green') if ok else ui.c('✗', 'red')} {d}" + ("" if ok else ui.c(f"   → {fix}", "dim")))
    if bad and not config_path().exists():
        found = [k for k in ("CEREBRAS_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY") if os.environ.get(k)]
        print(ui.c("  first run: no stack chosen yet. Keys found in .env: " + (", ".join(found) or "none"), "dim"))
        auto = setup.suggest_preset()
        names = {"cerebras": "Cerebras gpt-oss-120b (key found in .env)", "openai": "OpenAI (key found in .env)",
                 "free-keys": "free Gemini + Groq tiers (keys found in .env)", "local": "local only, no keys (needs Ollama; slower and weaker)"}
        choice = ui.ask("Which models do you want to use?", [(auto, names[auto] + "  (recommended)")] + [(k, v) for k, v in names.items() if k != auto], default=auto) or auto
        setup.setup(argparse.Namespace(preset=choice, llm_model="qwen2.5:3b", install=None, yes=False))
        cfg = load_config()
        rows, voice = setup.checks(cfg)
        bad = [r for r in rows if not r[1]]
    if bad:
        raise cli.UserError("the models are not ready yet. To fix: " + "; ".join(r[3] for r in bad[:2]),
                            "fix the ✗ lines above (keys go in .env, never in chat), then run `calleval start` again; `calleval setup` changes the stack")

    # 2 ---------------------------------------------------------------- agent
    stage(2, "Choosing the agent to test")
    have = sorted(p.name for p in (ROOT / "agents").glob("*") if p.is_dir())
    name = a.agent
    if not name:
        opts = [(h, f"{h} (already here)") for h in have] + [("__new", "Add my own agent (from scratch, a prompt, or a LiveKit agent file)")]
        name = ui.ask("Which agent do you want to test?", opts, default=("maya" if "maya" in have else (have[0] if have else "__new")))
    if name == "__new":
        before = set(have)
        cli.cmd_newagent(argparse.Namespace(name=None, prompt=None, tools=None, welcome=None, livekit_file=None, scratch=False))
        new = sorted(set(p.name for p in (ROOT / "agents").glob("*") if p.is_dir()) - before)
        if not new:
            raise cli.UserError("no agent was created", "run `calleval new-agent` and follow the prompts")
        name = new[0]
        print(ui.c(f"\n Open agents/{name}/v1/agent.json, set the greeting (and check the tool results), then run `calleval start --agent {name}`.", "yellow"))
        return
    agent = cli.agent_or_die(name, a.version)
    cli.preflight(agent)
    ui.line("✓", "green", f"{agent['name']} {agent['version']}", f"{len(agent['tools'])} tools, prompt {len(agent['prompt']):,} characters")

    # 3 ---------------------------------------------------------------- cases
    stage(3, "Choosing the test cases", "default cases that fit this agent, plus any written for it")
    has_gen = (ROOT / "cases" / "generated" / agent["name"]).exists()
    if not has_gen and not a.cases and agent["tools"] and (a.gen or ui.ask("Also write extra cases from this agent's prompt? (one model call, about a minute)", [("y", "yes"), ("n", "no")], default="n") == "y"):
        gencases.run(agent, 4)
    cases = pick_cases(agent, cfg, a.cases)
    if not cases:
        raise cli.UserError("no test case applies to this agent", "set case_vars in agent.json or run `calleval gen-cases --agent " + agent["name"] + "`")
    for c in cases:
        ui.line("✓", "green", f"{c['id']:34}", c.get("title", "")[:70])
    n_conv = len(cases) * a.runs
    print(ui.c(f"  {n_conv} conversation(s), roughly {max(1, n_conv * (3 if a.voice else 1))}–{n_conv * (4 if a.voice else 2)} minutes", "dim"))

    # 4 ---------------------------------------------------------------- run
    run_id = a.run_id or time.strftime("start-%m%d-%H%M")
    stage(4, "Running the conversations" + (" (real audio)" if a.voice else " (text)"), "the customer bot talks to your agent; tools hit the fake backend")
    ids = ",".join(c["id"] for c in cases)
    if a.voice:
        if [r for r in voice if not r[1]]:
            raise cli.UserError("voice runs need the extra pieces", "run `calleval setup --install voice` first")
        cli.cmd_voice(argparse.Namespace(agent=agent["name"], version=agent["version"], cases=ids, split="all", runs=a.runs, run_id=run_id))
    else:
        cli.cmd_run(argparse.Namespace(agent=agent["name"], version=agent["version"], cases=ids, split="all", runs=a.runs, turns=None, run_id=run_id))

    # 5 ---------------------------------------------------------------- judge
    stage(5, "Judging", "an LLM reads each conversation against its criteria and quotes evidence")
    if a.judge == "claude":
        cli.cmd_judge(argparse.Namespace(run_id=run_id, llm=False))
        print(ui.c(" Open Claude Code in this folder and say: judge run " + run_id + " with calleval. Then run `calleval report " + run_id + "`.", "yellow"))
        return
    cli.cmd_judge(argparse.Namespace(run_id=run_id, llm=True))

    # 6 ---------------------------------------------------------------- results
    stage(6, "Results")
    base = ROOT / "runs" / run_id
    cli.cmd_report(argparse.Namespace(run_id=run_id))
    fails = explain(run_id)

    # 7 ---------------------------------------------------------------- report in the browser
    stage(7, "Opening the report", "chat view, evidence highlighted, reasons" + (", audio" if a.voice else ""))
    uri = (base / "report.html").resolve().as_uri()
    print(f"  {ui.c(uri, 'cyan', 'bold')}")
    shown = False
    if not a.no_open and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or sys.platform in ("darwin", "win32")):
        try:
            shown = webbrowser.open(uri)
        except Exception:
            shown = False
    print(ui.c("  opened in your browser" if shown else "  open the link above in a browser", "dim"))

    print(ui.c(f"\n Done in {(time.time() - t_all) / 60:.1f} min.", "bold"))
    if fails and ui.ask("Propose a better prompt from these failures now? (writes a new version; does not touch the old one)", [("y", "yes"), ("n", "no")], default="n") == "y":
        cli.cmd_improve(argparse.Namespace(agent=agent["name"], version=agent["version"], from_run=run_id))
    elif fails:
        ui.hint(f"calleval improve --agent {agent['name']} --from {run_id}    (writes a new prompt version from the failures)")
    if not a.voice:
        ui.hint("for real audio: calleval setup --install voice, then calleval start --voice   |   for more confidence: --runs 3")
