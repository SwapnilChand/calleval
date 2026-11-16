---
name: calleval
description: Test a voice agent with simulated customers and a judge. Use when the user wants to evaluate, stress-test or improve a voice agent's prompt (any prompt-based agent), add test cases, judge a run, or produce a pass/fail report.
---

# calleval

Project root = the folder with `calleval.sh`. All state is plain files (agents/, cases/, runs/). Commit prompt versions with git. Never name or depend on a specific agent platform; the user's prompt and tools are the interface.

## 1. Onboard (a conversation: one question at a time, never ask the user to paste keys in chat)
Everything runs on the user's machine. Keys are optional; they only buy better models. Start with `./calleval.sh doctor` and show the result.
1. **Ask what they are starting from** (one question, three options): (a) **building from scratch**: `./calleval.sh new-agent <name> --scratch` copies `templates/prompt.md` (section layout: identity/tone/tool rules/language/numbers/escalation/normalization/guardrails, then opening+lookup, intent branches, flows with exact lines + Instructions + tool-response handling, closing, FAQs); ask for role, business facts, tools and languages, fill the placeholders, keep the layout, and design the tools with them (names, parameters, what each returns). (b) **a prompt (and maybe a tools file)**: `./calleval.sh new-agent <name> --prompt <file> [--tools tools.json] [--welcome "first line"]`. (c) **a LiveKit agent file** (Python): `./calleval.sh new-agent <name> --livekit-file <file>`; the file is parsed, never run, and its instructions, `@function_tool` definitions (types, enums, docstrings) and speech stack are read exactly, so nothing is guessed. Running `new-agent` with no arguments asks the same question. (d) just trying it: the bundled demo `maya` (clinic receptionist) or `dental` (imported from `examples/livekit_agent.py`).
2. **Finish the agent's `agent.json`.** For (c) most of it is filled: check the assumed tool roles in `case_vars`, write the line the agent usually says first into `welcome` (runs refuse to start while it is a TODO), and give each tool a realistic result in `mock.tools` (the CLI keeps literal returns from the file and flags computed ones). For (a) and (b) without a tools file, **infer the tools from the prompt and confirm**: draft each tool's name, parameters (types, formats, enums) and a realistic result for each outcome the prompt handles into `tools`, `mock.tools`, `mock.formats`; set `case_vars` (task, book_tool, lookup_tool, change_tool, transfer_tool, caller_tool: which tool plays which role; omit a role and the cases needing it are skipped). Show the draft in plain words ("I found 5 tools: ..., here is what I assume each returns") and ask them to confirm or correct it; say clearly it is inferred. Exact definitions the user has are always better. The tools run against this fake backend, never a real system.
3. **Choose the stack** (explain each in one line, ask which):
   - `local` (default, no keys, nothing leaves the machine): Ollama for the language models, faster-whisper for speech-to-text, Piper for speech. Slowest; small local models follow long prompts and tools poorly. Needs Ollama running with a model pulled (`ollama pull qwen2.5:3b`, about 2 GB).
   - `free-keys`: Gemini (language models) + Groq (speech-to-text) free tiers. The user adds `GEMINI_API_KEY` and `GROQ_API_KEY` to `.env` themselves. Free tiers are small: start with `--runs 1`.
   - custom: any OpenAI-compatible endpoint; edit `calleval.json` (`agent_llm`, `persona_llm`: base_url, model, key_env).
   Apply with `./calleval.sh setup --preset local|free-keys`; it writes `calleval.json` (personal, gitignored) and prints what is still missing. Re-run `./calleval.sh doctor` until text runs show OK.
4. **Smoke test:** `./calleval.sh run --agent <name> --cases relative-date-resolution --runs 1 --run-id smoke`, then judge and report it (sections 4-5) so the user sees the whole loop once.
5. **Voice (optional):** only if the user wants real audio. Offer `./calleval.sh setup --install voice` (about 600 MB; says what it installs, do not run without a yes), then section 3b.

## 2. Cases
- Quickest: `./calleval.sh gen-cases --agent <name> [--n 6]` writes cases from the agent's prompt with the configured model (status shown as it works, about a third marked held-out). You can also write them yourself (below), which usually gives sharper cases.
- Fixed suite: `cases/universal/core.json` (each case lists its `source`). Add more by dropping any `*.json` (a case or a list) under `cases/`.
- Prompt-derived: read the agent's prompt, list every promise, tool, constraint, handoff, language rule; write one case per item to `cases/generated/<agent>/<topic>.json`, same schema as core.json (persona, goal, quirks, precondition, criteria = yes/no statements, checks = deterministic tool-call or regex checks, mock_overrides). Mark ~30% `"split": "heldout"`.
- Every case needs a `precondition`: what the CUSTOMER must do for the test to count.

## 3. Run
`./calleval.sh run --agent <name> [--version vN] [--cases all|universal|generated|id,id] [--split train|heldout] [--runs N] --run-id <id>`
Resumes if interrupted (existing transcripts are skipped). Errors (e.g. 429 after retries) are recorded in the transcript.

## 3b. Voice run (real audio, local): `./calleval.sh voice-run --agent <a> --version vN --cases ... --run-id <id>`
What it does: starts a local livekit-server, two workers (twin = the agent under test rebuilt from agents/<a>/vN prompt + tools + mock backend; persona = the caller), puts both in one room, records each speaker's audio, runs detectors, writes the same transcript.json as text runs plus audio.mp3 and analysis.json. Judge and report then work unchanged (the judge input gets a "Voice analysis" section; the report shows chat bubbles, flags and audio).
Say plainly: the twin is a rebuild of the prompt and tools on the chosen speech and language services, so audio findings (misheard names, how numbers are spoken, latency) hold for those services, not for the customer's production voice stack.
Free quick probe, no audio: `./calleval.sh twin-debug --agent <a> --version vN`, then follow its printed `lk agent debugger` commands (needs the optional `lk` CLI in `.tools/`; text mode is free).
Reading results: analysis.json flags are hints with timestamps (slow_response, talk_over, agent_cut_off, repeat, dead_air, no_reply_after_tool, STT mismatches, spoken_forms from a listening model when GEMINI_API_KEY is set). Quote them as evidence in verdicts only when the transcript agrees; do not treat a flag as a verdict.

## 4. Judge (you are the judge; this uses the user's Claude subscription)
`./calleval.sh judge <run_id>` writes `judge_input.md` beside every transcript. For each one: read it, write `verdict.json` in the same folder in the exact format it states. Hard rules:
- Judge only from transcript and tool calls. Quote the exact words with their turn number (T<n>) for every criterion; no quote means pass:false.
- First decide `scenario_happened` from the precondition. If the customer never did the scenario, set false (run is VOID, not a pass).
- Credit actions, not intent. Be strict; do not grade on a curve.
- When something fails write `suggested_prompt_fix`: a concrete edit to the agent's prompt (a hypothesis, to be verified by re-running).
Fallback without Claude Code: `./calleval.sh judge <run_id> --llm`.

## 5. Report
`./calleval.sh report <run_id>` prints a table and writes `runs/<run_id>/report.html`. Status rule: any hard-check fail = FAIL; judge fails in >=2 of >=3 valid runs = FAIL, 1 = FLAKY; VOID runs are excluded. Open the report for the user.

## 6. Improve loop (versioned, held-out)
Shortcut: `./calleval.sh improve --agent <name> --from <run_id>` proposes the next prompt version from that run's failed train cases (it never reads held-out cases) and writes `CHANGES.md`; review the diff, commit, then verify as below. The manual steps:
1. Work only from failures in `--split train`. Never read held-out transcripts while editing the prompt.
2. `./calleval.sh new-version <agent>` then edit (put each fix in the section of `templates/prompt.md` where it belongs, e.g. a tool rule under Tool Execution Rules, a spoken-format rule under Spoken Numbers; don't append loose rules at the end) `agents/<agent>/vN/prompt.md` (one change at a time), `git add -A && git commit -m "maya v2: <what and why>"`.
3. Re-run the same train cases with `--version vN`, then run `--split heldout` for v1 and vN. Only claim improvement if held-out pass rate did not drop. Report both.
4. Caveat: the agent runs on the chosen stack, not its production LLM and voice services; confirm fixes in production-like conditions before shipping.
