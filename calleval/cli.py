import argparse, os, hashlib, json, shutil, sys, time
from pathlib import Path
from . import ui
from .core import ROOT, Skip, why_not, config_path, date_vars, fill, load_agent, load_cases, load_config, load_env, versions
from .judge import judge_input_md, llm_judge
from .report import load_runs, print_table, summarize, write_html
from .sim import run_conversation


def show(case_id, n, res, secs):
    err = res.get("error")
    ok = not err and res["turns"]
    ui.line("✓" if ok else "✗", "green" if ok else "red", f"{case_id:34} #{n}",
            f"{len(res['turns'])} turns · {len(res['tool_calls'])} tool calls · {res['ended']} · {secs:.0f}s" + (f" · {err[:90]}" if err else ""))
    return 0 if ok else 1


def stack_line(cfg):
    a, p = cfg["agent_llm"], cfg["persona_llm"]
    where = lambda c: "local" if any(h in c["base_url"] for h in ("127.0.0.1", "localhost")) else "hosted"
    return f"agent: {a.get('model', a['base_url'])} ({where(a)}) · persona: {p.get('model', p['base_url'])} ({where(p)})"


class UserError(Exception):
    """A mistake the user can fix; printed as one line, no traceback."""
    def __init__(self, msg, fix=""):
        super().__init__(msg)
        self.fix = fix


def agent_or_die(name, version=None):
    have = sorted(p.name for p in (ROOT / "agents").glob("*") if p.is_dir()) if (ROOT / "agents").exists() else []
    if name not in have:
        raise UserError(f"no agent called '{name}'", f"agents here: {', '.join(have) or 'none'}. Create one: calleval new-agent {name} --prompt prompt.md")
    if version and version not in [f"v{n}" for n in versions(name)]:
        raise UserError(f"agent '{name}' has no version '{version}'", f"versions: {', '.join(f'v{n}' for n in versions(name))}")
    return load_agent(name, version)


def preflight(agent):
    """Stop before spending time on an agent that is still a stub."""
    if str(agent.get("welcome", "")).startswith("TODO"):
        raise UserError(f"agent '{agent['name']}' has no greeting yet",
                        f"edit agents/{agent['name']}/{agent['version']}/agent.json and set \"welcome\" to the first line the agent says" +
                        (f" (the file's instruction was: {agent['welcome_instruction']})" if agent.get("welcome_instruction") else ""))
    if "TODO" in str(agent.get("case_vars", {}).get("task", "")):
        ui.line("!", "yellow", "case_vars.task is still a TODO: some cases will use a vague description of what customers want")


def cmd_newagent(a):
    """Add an agent: from scratch (template), from a prompt (+ tools json), or from a LiveKit agent file. Asks when run without arguments."""
    name = a.name or ui.ask("Name for this agent (a short folder name, e.g. clinic)", default="")
    if not name:
        raise UserError("an agent name is required", "calleval new-agent <name> [--prompt FILE | --livekit-file FILE]")
    source = "livekit" if a.livekit_file else "prompt" if a.prompt else "scratch" if a.scratch else None
    if not source:
        source = ui.ask("What are you starting from?", [
            ("scratch", "I'm building an agent from scratch (start from a prompt template)"),
            ("prompt", "I have a prompt (and maybe a tools file)"),
            ("livekit", "I have a LiveKit agent file (Python). Its instructions and tools can be read directly, no guessing")], default="scratch")
    d = ROOT / "agents" / name / "v1"
    if d.exists():
        raise UserError(f"agent '{name}' already exists", f"add a new prompt version instead: calleval new-version {name}")
    if source == "livekit":
        from .lkimport import extract, to_agent_json
        f = a.livekit_file or ui.ask("Path to the LiveKit agent file", default="")
        if not f or not Path(f).exists():
            raise UserError(f"file not found: {f or '(none given)'}", "give the path to the .py file that defines your agent")
        ui.step(f"reading {f} (the file is parsed, never run)")
        found = extract(Path(f).read_text())
        d.mkdir(parents=True)
        (d / "prompt.md").write_text(found["instructions"] or "TODO: paste the agent's instructions here\n")
        ui.line("✓" if found["instructions"] else "!", "green" if found["instructions"] else "yellow",
                f"instructions: {len(found['instructions'] or '')} characters" if found["instructions"] else "instructions not found")
        ui.line("✓" if found["tools"] else "!", "green" if found["tools"] else "yellow",
                f"tools: {', '.join(t['function']['name'] for t in found['tools']) or 'none found'}")
        data, roles = to_agent_json(name, found)
        (d / "agent.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
        ui.line("✓", "green", "speech stack in the file: " + (", ".join(f"{k}={v}" for k, v in found["stack"].items()) or "not found"),
                "kept as a note; tests use the stack you chose in `calleval setup`")
        if roles:
            ui.line("✓", "green", "assumed tool roles: " + ", ".join(f"{k.replace('_tool', '')}={v}" for k, v in roles.items()), "check case_vars in agent.json")
        for n_ in found["notes"]:
            ui.line("!", "yellow", n_)
        if found["welcome"]:
            ui.line("!", "yellow", "the greeting is generated at runtime (instruction kept); write the line it usually says into agent.json 'welcome'")
        ui.hint(f"review {d.relative_to(ROOT)}/agent.json (welcome line, mock results), then `calleval gen-cases --agent {name}`")
        cmd_fit(argparse.Namespace(agent=name, version=None))                   # research which tests suit the imported agent
        return
    d.mkdir(parents=True)
    if a.prompt:
        ui.step(f"copying {a.prompt}")
        shutil.copy(a.prompt, d / "prompt.md")
    else:
        ui.step("copying the prompt template (templates/prompt.md)")
        shutil.copy(ROOT / "templates" / "prompt.md", d / "prompt.md")
    tools = json.loads(Path(a.tools).read_text()) if a.tools else []
    tools = [t if "function" in t else {"type": "function", "function": t} for t in tools]
    (d / "agent.json").write_text(json.dumps({"name": name, "welcome": a.welcome or "TODO: first line the agent says",
        "tools": tools, "mock": {"tools": {}, "formats": {}}, "case_vars": {"task": "TODO: what a customer calls this agent for"}}, indent=2))
    ui.line("✓", "green", f"created {d.relative_to(ROOT)}" + (f" with {len(tools)} tool(s)" if tools else ""))
    ui.hint(f"edit {d.relative_to(ROOT)}/agent.json (welcome line, case_vars, mock tool results)"
            + ("; ask Claude Code to write the prompt from the template (`/calleval`)" if source == "scratch" else ""))
    if source == "prompt":
        cmd_fit(argparse.Namespace(agent=name, version=None))


def cmd_newver(a):
    agent_or_die(a.agent)
    n = versions(a.agent)[-1]
    src, dst = ROOT / "agents" / a.agent / f"v{n}", ROOT / "agents" / a.agent / f"v{n+1}"
    shutil.copytree(src, dst)
    ui.line("✓", "green", f"created {dst.relative_to(ROOT)} (copy of v{n})")
    ui.hint(f"edit {dst.relative_to(ROOT)}/prompt.md, commit it, then `calleval run --agent {a.agent} --version v{n+1}`")


def cmd_run(a):
    cfg = load_config()
    if a.turns:
        cfg["turns"] = a.turns
    agent = agent_or_die(a.agent, a.version)
    preflight(agent)
    dv = date_vars(cfg["now"])
    cvars = {**dv, **agent.get("case_vars", {})}
    run_id = a.run_id or time.strftime("%Y%m%d-%H%M")
    runs = a.runs or cfg["runs"]
    base = ROOT / "runs" / run_id
    base.mkdir(parents=True, exist_ok=True)
    (base / "run.json").write_text(json.dumps({"config": {k: cfg[k] for k in ("agent_llm", "persona_llm", "now", "turns")},
        "prompt_sha": hashlib.sha1(agent["prompt"].encode()).hexdigest()[:10]}, indent=1))
    cases = load_cases(a.cases, a.split, a.agent)
    ui.header("calleval run", f"{agent['name']} {agent['version']}", f"{len(cases)} cases × {runs} run(s)", f"≤{cfg['turns']} turns", f"id {run_id}")
    print(ui.c(f" {stack_line(cfg)}", "dim"))
    done = errs = 0
    t_all = time.time()
    for c in cases:
        if (w := why_not(agent, c, cfg)):
            ui.line("-", "dim", f"{c['id']:34} skipped", w)
            continue
        case = fill(c, cvars)
        for n in range(1, runs + 1):
            d = base / f"{agent['name']}-{agent['version']}" / case["id"] / str(n)
            if (d / "transcript.json").exists():
                continue                                         # resume: don't re-spend tokens
            pvars = {"current_date": f"{dv['weekday']}, {dv['today']}", "current_time": dv["time"],
                     "from_number": case.get("caller", cfg["from_number"])}
            t1 = time.time()
            res = run_conversation(agent, case, cfg, pvars)
            err = res.get("error") or ""
            if any(k in err for k in ("Connection refused", "missing env var", "Name or service not known", "HTTP Error 401", "HTTP Error 403", "HTTP 429", "HTTP 401", "HTTP 403")):
                raise UserError(f"the model is not reachable: {err[:140]}",
                                "local models: start `ollama serve`; hosted: check the key in .env, or a free-tier quota (429) is used up: wait or switch model in calleval.json. Nothing was saved for this case, so a re-run starts clean.")
            d.mkdir(parents=True, exist_ok=True)
            (d / "transcript.json").write_text(json.dumps({"agent": agent["name"], "version": agent["version"],
                "run": n, "case": case, **res}, indent=1, ensure_ascii=False))
            errs += show(case["id"], n, res, time.time() - t1)
            done += 1
    print(ui.c(f"\n {done} conversation(s), {errs} with errors, {time.time() - t_all:.0f}s", "bold"))
    ui.hint(f"calleval judge {run_id}   (then: calleval report {run_id})")


def cmd_voice(a):
    import asyncio
    from .voice.runner import Stack, one_call
    from .voice.spec import build_spec
    cfg = load_config()
    agent = agent_or_die(a.agent, a.version)
    preflight(agent)
    dv = date_vars(cfg["now"])
    cvars = {**dv, **agent.get("case_vars", {})}
    run_id = a.run_id or time.strftime("voice-%Y%m%d-%H%M")
    base = ROOT / "runs" / run_id
    base.mkdir(parents=True, exist_ok=True)
    cases = load_cases(a.cases, a.split, a.agent)
    ui.header("calleval voice-run", f"{agent['name']} {agent['version']}", f"{len(cases)} cases", f"id {run_id}")
    v = cfg["voice"]
    print(ui.c(f" speech-to-text: {v['stt']} · text-to-speech: {v['tts']} · {stack_line(cfg)}", "dim"))
    print(ui.c(" starting local LiveKit server and workers…", "dim"))
    stack = Stack(cfg["voice"], base / "_stack")
    stack.start()
    done = errs = 0
    t_all = time.time()
    try:
        for c in cases:
            if (w := why_not(agent, c, cfg)):
                ui.line("-", "dim", f"{c['id']:34} skipped", w)
                continue
            case = fill(c, cvars)
            for n in range(1, (a.runs or 1) + 1):
                d = base / f"{agent['name']}-{agent['version']}" / case["id"] / str(n)
                if (d / "transcript.json").exists():
                    continue
                pvars = {"current_date": f"{dv['weekday']}, {dv['today']}", "current_time": dv["time"],
                         "from_number": case.get("caller", cfg["from_number"])}
                spec = build_spec(agent, case, cfg, pvars, d)
                t1 = time.time()
                res = asyncio.run(one_call(cfg["voice"], d / "spec.json", json.loads((d / "spec.json").read_text()), d))
                (d / "transcript.json").write_text(json.dumps({"agent": agent["name"], "version": agent["version"],
                    "run": n, "case": case, "mode": "voice", **res}, indent=1, ensure_ascii=False))
                errs += show(case["id"], n, res, time.time() - t1)
                done += 1
    finally:
        stack.stop()
    print(ui.c(f"\n {done} call(s), {errs} with errors, {time.time() - t_all:.0f}s. audio: runs/{run_id}/<agent>/<case>/<n>/audio.mp3", "bold"))
    ui.hint(f"calleval judge {run_id}   (then: calleval report {run_id})")


def cmd_twindebug(a):
    """Write a spec for the agent's voice twin and print the LiveKit debugger commands (free text mode; you or Claude Code play the caller)."""
    from .voice.spec import build_spec
    cfg = load_config()
    agent = agent_or_die(a.agent, a.version)
    dv = date_vars(cfg["now"])
    case = {"id": "debug", "persona": "a caller", "goal": "n/a", "quirks": [], "criteria": []}
    pvars = {"current_date": f"{dv['weekday']}, {dv['today']}", "current_time": dv["time"], "from_number": cfg["from_number"]}
    d = ROOT / "runs" / "_debug" / f"{agent['name']}-{agent['version']}"
    p = build_spec(agent, case, cfg, pvars, d)
    print(f"spec: {p}\nnow run:\n  export CALLEVAL_SPEC={p}\n  .tools/lk agent debugger start calleval/voice/debug_agent.py\n"
          f"  .tools/lk agent debugger say \"I need an appointment tomorrow at 10 AM\"   # repeat; add --logs to see tool calls\n  .tools/lk agent debugger stop")


def cmd_doctor(a):
    from .setup import doctor
    raise SystemExit(0 if doctor(a) else 1)


def cmd_setup(a):
    from .setup import setup
    setup(a)


def run_dir_or_die(run_id):
    base = ROOT / "runs" / run_id
    if not base.exists():
        have = sorted(p.name for p in (ROOT / "runs").glob("*") if p.is_dir() and not p.name.startswith("_")) if (ROOT / "runs").exists() else []
        raise UserError(f"no run called '{run_id}'", f"runs here: {', '.join(have[-8:]) or 'none yet'}. Start one: calleval run --agent <name> --run-id {run_id}")
    return base


def cmd_gencases(a):
    from .gencases import run
    agent = agent_or_die(a.agent, a.version)
    ui.header("calleval gen-cases", f"{agent['name']} {agent['version']}", f"{a.n} cases")
    out = run(agent, a.n)
    if not out:
        raise UserError("the model did not return usable test cases", "try again, or use a stronger model (`calleval setup --preset free-keys`); Claude Code can also write them (the skill)")
    ui.line("✓", "green", f"wrote {out.relative_to(ROOT)}", "review and edit it; about a third are held out for the improve loop")
    ui.hint(f"calleval run --agent {agent['name']} --cases generated --runs 1 --run-id gen1")


def cmd_fit(a):
    """After importing an agent: which tests suit it, and why not for the rest. Reads its prompt and tools; saved to agents/<name>/fit.json."""
    cfg = load_config()
    agent = agent_or_die(a.agent, a.version)
    ui.header("calleval fit", f"{agent['name']} {agent['version']}", f"languages supported: {', '.join(cfg['languages'])}")
    fit = {}
    for c in load_cases("all", "all", agent["name"], all_languages=True):
        w = why_not(agent, c, cfg)
        fit[c["id"]] = {"applies": not w, "reason": w or "ok"}
        ui.line("✓" if not w else "-", "green" if not w else "dim", f"{c['id']:34} {'applies' if not w else 'not suitable'}", w or "")
    (ROOT / "agents" / agent["name"] / "fit.json").write_text(json.dumps(fit, indent=1, ensure_ascii=False) + "\n")
    n = sum(v["applies"] for v in fit.values())
    ui.hint(f"{n} of {len(fit)} cases suit this agent; the rest are skipped automatically. Wrong call? Edit the agent's prompt/tools or the case's needs_prompt, then rerun `calleval fit`.")


def cmd_improve(a):
    from .improve import run
    agent = agent_or_die(a.agent, a.version)
    run_dir_or_die(a.from_run)
    ui.header("calleval improve", f"{agent['name']} {agent['version']}", f"from run {a.from_run}")
    res = run(agent["name"], agent["version"], a.from_run)
    if res is None:
        raise UserError("no failed train-split cases to learn from in that run", f"judge and report it first (calleval judge {a.from_run}), or pick a run with failures")
    if res == "bad":
        raise UserError("the model did not return a usable prompt", "try again, or use a stronger model (`calleval setup --preset free-keys`)")
    ui.hint(f"git add -A && git commit -m \"{agent['name']} v{res}: proposed fixes\"; then verify: "
            f"calleval run --agent {agent['name']} --version v{res} --split train --run-id try{res}  and the same with --split heldout for both versions")


def cmd_demo(a):
    """Replay a real recorded voice run (Maya v2, 11 cases, judged) so you can see the report with no keys and no setup."""
    src, dst = ROOT / "examples" / "sample-run", ROOT / "runs" / "demo"
    if not src.exists():
        raise UserError("the bundled sample run is missing", "re-clone the repository")
    ui.header("calleval demo", "a real recorded voice run", "no keys needed")
    ui.step("copying the sample run to runs/demo (the bundled files stay untouched)")
    shutil.copytree(src, dst, dirs_exist_ok=True)
    cmd_report(argparse.Namespace(run_id="demo"))
    print(ui.c("\n Open the report and click a case: chat view, the evidence turns highlighted, the judge's reasoning, voice analysis,", "dim"))
    print(ui.c(" and (for asks-name-never-invents) the real call audio. Then try `calleval doctor` to start with your own agent.", "dim"))


def cmd_start(a):
    from .start import run
    run(a)


def cmd_live(a):
    """Talk to the REAL hosted agent over its streaming socket (no twin): real speech-to-text, voice, model and latency."""
    import asyncio, importlib
    for mod in ("aiohttp", "faster_whisper", "piper"):
        try:
            importlib.import_module(mod)
        except ImportError:
            raise UserError("live runs need the voice pieces", "run `calleval setup --install voice` first")
    from .live import bolna
    from .live.runner import Voice, converse, write_run
    from .sim import PERSONA
    cfg = load_config()
    agent = agent_or_die(a.agent, a.version)
    live = cfg.get("live", {}).get("agents", {}).get(agent["name"], {})
    agent_id = a.provider_agent_id or live.get("agent_id")
    if not agent_id:
        raise UserError("no hosted agent is linked to this agent yet", f"calleval live-run --agent {agent['name']} --provider-agent-id <the agent's id on the provider>")
    if a.provider_agent_id:                                   # remember it in your personal config
        p = config_path()
        cur = json.loads(p.read_text()) if p.exists() else {}
        cur.setdefault("live", {}).setdefault("agents", {})[agent["name"]] = {"provider": "bolna", "agent_id": agent_id}
        p.write_text(json.dumps(cur, indent=2) + "\n")
    dv = date_vars(cfg["now"])
    cvars = {**dv, **agent.get("case_vars", {})}
    cases = []
    for c in load_cases(a.cases, a.split, agent["name"]):
        if c.get("mock_overrides"):
            ui.line("-", "dim", f"{c['id']:34} skipped", "needs a forced tool failure; only possible in text and voice-twin runs")
            continue
        if not why_not(agent, c, cfg):
            cases.append(fill(c, cvars))
    if not cases:
        raise UserError("no case can run live for this agent", "pick cases with --cases id,id")
    n = len(cases) * a.runs
    ui.header("calleval live-run", f"{agent['name']} (hosted agent {agent_id[:8]}…)", f"{n} call(s)", f"≤{a.max_minutes} min total")
    print(ui.c("  This talks to your REAL agent: its real tools run (a booking test can create a real booking) and the provider bills minutes.", "yellow"))
    if not a.real_tools and ui.ask("Go ahead with the real agent and its real tools?", [("y", "yes"), ("n", "no")], default="n") != "y":
        raise UserError("not confirmed", "re-run with --real-tools to confirm, or use text / voice-run (fake backend)")
    adp = bolna.Adapter(agent_id, host=live.get("host"))
    before = adp.balance()
    ui.step("loading local speech models (first time downloads about 150 MB)")
    voice = Voice(cfg)
    run_id = a.run_id or time.strftime("live-%m%d-%H%M")
    base = ROOT / "runs" / run_id
    start_all, done, errs = time.time(), 0, 0
    for case in cases:
        for k in range(1, a.runs + 1):
            if (time.time() - start_all) / 60 > a.max_minutes:
                ui.line("!", "yellow", "time budget reached; stopping (finished calls are kept)")
                break
            d = base / f"{agent['name']}-{agent['version']}" / case["id"] / str(k)
            if (d / "transcript.json").exists():
                continue
            pvars = {"from_number": case.get("caller", cfg["from_number"])}
            persona = PERSONA.format(persona=case["persona"], goal=case["goal"], phone=pvars["from_number"], quirks="; ".join(case.get("quirks", [])) or "none")
            ui.step(f"calling the agent: {case['id']} #{k}")
            t1 = time.time()
            res = asyncio.run(converse(adp, voice, cfg, persona, cfg["turns"], 150))
            rec = adp.find_execution(t1)
            tr = write_run(d, res, rec, case, {"agent": agent["name"], "version": agent["version"], "run": k, "provider": "bolna"})
            errs += show(case["id"], k, {"turns": tr["turns"], "tool_calls": [], "ended": tr["ended"], "error": None}, time.time() - t1)
            done += 1
    after = adp.balance()
    print(ui.c(f"\n {done} call(s), {errs} with problems, {(time.time() - start_all) / 60:.1f} min" + (f", spent {before - after:.2f} wallet units" if before is not None and after is not None else ""), "bold"))
    ui.hint(f"calleval judge {run_id} --llm   (then: calleval report {run_id})")


def cmd_judge(a):
    cfg = load_config()
    base = run_dir_or_die(a.run_id)
    pending = 0
    for tp in sorted(base.rglob("transcript.json")):
        if (tp.parent / "verdict.json").exists():
            continue
        t = json.loads(tp.read_text())
        if a.llm:
            try:
                (tp.parent / "verdict.json").write_text(json.dumps(llm_judge(cfg, t), indent=1))
                ui.line("✓", "green", f"judged {tp.parent.relative_to(base)}")
            except Exception as e:
                ui.line("✗", "red", f"judge failed {tp.parent.relative_to(base)}", str(e)[:120])
        else:
            (tp.parent / "judge_input.md").write_text(judge_input_md(t))
            pending += 1
    if not a.llm:
        ui.line("✓", "green", f"wrote {pending} judge_input.md file(s) under runs/{a.run_id}/")
        ui.hint("Claude Code reads each judge_input.md and writes verdict.json beside it (the skill explains how); "
                f"or run `calleval judge {a.run_id} --llm` to use a language model instead. Then `calleval report {a.run_id}`.")


def cmd_report(a):
    base = run_dir_or_die(a.run_id)
    summary = summarize(load_runs(base))
    print_table(summary)
    write_html(summary, base / "report.html", f"calleval report · {a.run_id}")
    ui.hint(f"open {base / 'report.html'} in a browser")


HELP = f"""{ui.c("calleval", "bold", "cyan")} · test a voice agent with simulated customers and a judge. Runs on your machine; keys are optional.

{ui.c("Usage", "bold")}  calleval <command> [options]      (calleval <command> -h for examples)

{ui.c("Get started", "bold")}
  start         one guided command: setup check, run, judge, results, report in the browser
  demo          see a real recorded run and its report, with no keys and no setup
  doctor        check what works and what is missing
  setup         pick a stack (local: no keys, or free-keys) and install the optional voice pieces
  new-agent     add your agent: from scratch, your prompt (+ tools), or a LiveKit agent file
  fit           which tests suit your agent (and why the others are skipped)
  gen-cases     write test cases from the agent's own prompt and tools

{ui.c("Test", "bold")}
  run           text conversations, persona <-> agent (fast, cheap; use several runs per case)
  voice-run     real audio calls on a local server (slower; finds speech problems like misheard names)
  judge         prepare each conversation for judging (Claude Code writes verdicts, or --llm)
  report        pass/fail table and runs/<id>/report.html (chat view, evidence, audio)

{ui.c("Improve", "bold")}
  improve       propose a better prompt (new version) from a run's failed cases
  new-version   copy the prompt to a new version to edit, commit and re-run
  twin-debug    free text probe of the voice twin with the LiveKit debugger

{ui.c("The loop", "bold")}  run -> judge -> report -> edit prompt (new-version) -> run again
"""


def next_step():
    ag = sorted(p.name for p in (ROOT / "agents").glob("*") if p.is_dir()) if (ROOT / "agents").exists() else []
    if not (ROOT / "calleval.json").exists():
        return "calleval doctor    (then: calleval setup)"
    if not ag:
        return "calleval new-agent myagent --prompt prompt.md --tools tools.json"
    return f"calleval run --agent {ag[0]} --cases relative-date-resolution --runs 1 --run-id smoke"


def build_parser():
    F = argparse.RawDescriptionHelpFormatter
    p = argparse.ArgumentParser(prog="calleval", add_help=False)
    p.print_help = lambda *_: print(HELP)
    p.add_argument("-h", "--help", action="store_true")
    s = p.add_subparsers(dest="cmd", metavar="<command>")

    def cmd(name, summary, example, f):
        x = s.add_parser(name, help=summary, description=summary, epilog="examples:\n" + example, formatter_class=F)
        x.set_defaults(f=f)
        return x
    x = cmd("new-agent", "Add an agent to test: from scratch, from your prompt (+ tools), or from a LiveKit agent file. Asks when run without arguments.",
            "  calleval new-agent                                  # asks\n  calleval new-agent clinic --livekit-file agent.py   # reads instructions + tools from the file\n  calleval new-agent clinic --prompt prompt.md --tools tools.json\n  calleval new-agent clinic --scratch", cmd_newagent)
    x.add_argument("name", nargs="?", help="agent name (asked if omitted)"); x.add_argument("--prompt", metavar="FILE", help="file with your agent's system prompt")
    x.add_argument("--livekit-file", metavar="FILE", help="a LiveKit agent .py file: instructions and tools are read from it"); x.add_argument("--scratch", action="store_true", help="start from the prompt template")
    x.add_argument("--tools", metavar="FILE", help="json file: list of OpenAI-style function tools"); x.add_argument("--welcome", help="the agent's first line")
    x = cmd("new-version", "Copy an agent's latest prompt to a new version folder (edit it, commit it, re-run).", "  calleval new-version maya", cmd_newver)
    x.add_argument("agent")
    x = cmd("run", "Run text conversations between the persona and your agent (judge them next).",
            "  calleval run --agent maya --runs 1 --run-id first\n  calleval run --agent maya --cases universal --runs 3 --run-id full\n  calleval run --agent maya --split heldout --version v2", cmd_run)
    x.add_argument("--agent", required=True, metavar="NAME"); x.add_argument("--version", metavar="vN", help="default: latest")
    x.add_argument("--cases", default="all", help="all | universal | generated | id,id  (default all)"); x.add_argument("--split", default="all", choices=["all", "train", "heldout"])
    x.add_argument("--runs", type=int, help="conversations per case (default 3; 1 is a quick look, 3 separates real issues from flukes)")
    x.add_argument("--turns", type=int, help="max customer turns"); x.add_argument("--run-id", metavar="ID", help="default: timestamp")
    x = cmd("voice-run", "Real audio calls: your agent (rebuilt as a voice twin) talks to the persona on a local server. Needs `calleval setup --install voice`.",
            "  calleval voice-run --agent maya --cases relative-date-resolution --run-id v1\n  calleval voice-run --agent maya --split train --run-id vcmp", cmd_voice)
    x.add_argument("--agent", required=True, metavar="NAME"); x.add_argument("--version", metavar="vN")
    x.add_argument("--cases", default="all"); x.add_argument("--split", default="all"); x.add_argument("--runs", type=int, help="calls per case (default 1)")
    x.add_argument("--run-id", dest="run_id", metavar="ID")
    x = cmd("twin-debug", "Free, text-only probe of the voice twin through the LiveKit debugger (you or Claude Code play the caller).", "  calleval twin-debug --agent maya", cmd_twindebug)
    x.add_argument("--agent", required=True, metavar="NAME"); x.add_argument("--version", metavar="vN")
    x = cmd("gen-cases", "Write test cases from the agent's own prompt and tools, using the configured language model.", "  calleval gen-cases --agent maya\n  calleval gen-cases --agent dental --n 8", cmd_gencases)
    x.add_argument("--agent", required=True, metavar="NAME"); x.add_argument("--version", metavar="vN"); x.add_argument("--n", type=int, default=6, help="how many cases (default 6)")
    x = cmd("fit", "Which tests suit this agent (from its prompt, tools and your speech stack), and why the others do not.", "  calleval fit --agent maya", cmd_fit)
    x.add_argument("--agent", required=True, metavar="NAME"); x.add_argument("--version", metavar="vN")
    x = cmd("improve", "Propose a revised prompt as a new version, from the failed train-split cases of a run (the self-improving loop).", "  calleval improve --agent maya --from vcmp", cmd_improve)
    x.add_argument("--agent", required=True, metavar="NAME"); x.add_argument("--version", metavar="vN", help="default: latest"); x.add_argument("--from", dest="from_run", required=True, metavar="RUN_ID")
    x = cmd("start", "One guided command: check setup, pick the agent, run, judge, show results, open the report. Status after every stage.",
            "  calleval start                       # asks what it needs\n  calleval start --agent maya --yes    # no questions, defaults\n  calleval start --agent maya --voice --runs 1", cmd_start)
    x.add_argument("--agent", metavar="NAME"); x.add_argument("--version", metavar="vN"); x.add_argument("--cases", help="id,id (default: a quick, relevant set)")
    x.add_argument("--runs", type=int, default=1, help="conversations per case (default 1; 3 separates real issues from flukes)")
    x.add_argument("--voice", action="store_true", help="real audio calls instead of text (needs `calleval setup --install voice`)")
    x.add_argument("--judge", choices=["llm", "claude"], default="llm", help="llm: automatic (default); claude: prepare for Claude Code to judge")
    x.add_argument("--gen", action="store_true", help="also write extra cases from the prompt"); x.add_argument("--no-open", action="store_true", help="do not open the browser")
    x.add_argument("--yes", action="store_true", help="no questions: use defaults"); x.add_argument("--run-id", dest="run_id", metavar="ID")
    x = cmd("live-run", "Talk to your REAL hosted agent over its streaming socket: real speech-to-text, voice, model and latency (needs the voice pieces; the provider bills minutes).",
            "  calleval live-run --agent maya --provider-agent-id <id> --cases relative-date-resolution --real-tools", cmd_live)
    x.add_argument("--agent", required=True, metavar="NAME"); x.add_argument("--version", metavar="vN"); x.add_argument("--cases", default="all"); x.add_argument("--split", default="all")
    x.add_argument("--runs", type=int, default=1); x.add_argument("--provider-agent-id", metavar="ID", help="the agent's id on the provider (saved to your config)")
    x.add_argument("--max-minutes", type=float, default=8, help="stop starting new calls after this many minutes (default 8)")
    x.add_argument("--real-tools", action="store_true", help="confirm that the real agent's real tools will run"); x.add_argument("--run-id", dest="run_id", metavar="ID")
    x = cmd("demo", "See what a report looks like: replays a real recorded voice run (no keys, no setup).", "  calleval demo", cmd_demo)
    x = cmd("doctor", "Check what works and what is missing for text runs and voice runs.", "  calleval doctor\n  calleval doctor --json", cmd_doctor)
    x.add_argument("--json", action="store_true")
    x = cmd("setup", "Choose a stack and write calleval.json; optionally install the voice pieces (about 600 MB).",
            "  calleval setup --preset local            # no keys, runs on this machine\n  calleval setup --preset free-keys        # Gemini + Groq free tiers (keys in .env)\n  calleval setup --install voice", cmd_setup)
    x.add_argument("--preset", choices=["local", "free-keys", "openai", "cerebras"]); x.add_argument("--llm-model", default="qwen2.5:3b", help="model name for the local preset")
    x.add_argument("--install", choices=["voice"]); x.add_argument("--yes", action="store_true", help="answer yes to install prompts")
    x = cmd("judge", "Prepare each conversation of a run for judging (judge_input.md); Claude Code writes verdict.json, or use --llm.", "  calleval judge first\n  calleval judge first --llm", cmd_judge)
    x.add_argument("run_id"); x.add_argument("--llm", action="store_true", help="use judge_llm instead of Claude Code")
    x = cmd("report", "Print the pass/fail table for a run and write runs/<id>/report.html.", "  calleval report first", cmd_report)
    x.add_argument("run_id")
    return p


def main(argv=None):
    load_env()
    p = build_parser()
    a = p.parse_args(argv)
    if a.help or not a.cmd:
        print(HELP)
        ui.hint(next_step())
        return
    try:
        a.f(a)
    except KeyboardInterrupt:
        print(ui.c("\n interrupted. Runs resume where they stopped: run the same command again.", "yellow"))
        raise SystemExit(130)
    except UserError as e:
        ui.error(str(e), e.fix)
        raise SystemExit(2)
    except Exception as e:
        if os.environ.get("CALLEVAL_DEBUG"):
            raise
        import urllib.error
        if isinstance(e, (urllib.error.URLError, ConnectionError)) and not isinstance(e, urllib.error.HTTPError):
            ui.error(f"cannot reach a model server ({getattr(e, 'reason', e)})", "is it running? `calleval doctor` shows what is missing (local models need `ollama serve`)")
        elif isinstance(e, urllib.error.HTTPError):
            ui.error(f"the model server answered HTTP {e.code}", "401/403: check the key in .env; 429: rate limit, wait or use fewer runs; 404: wrong model name in calleval.json")
        else:
            ui.error(f"{type(e).__name__}: {e}", "set CALLEVAL_DEBUG=1 to see the full traceback")
        raise SystemExit(1)
