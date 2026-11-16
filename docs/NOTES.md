# calleval notes (built 2026-11-16, unattended)

## Measured on Groq free (2026-11-16, one 7-turn conversation, gpt-oss-20b agent + gpt-oss-120b persona)
9 calls, 40,977 prompt tokens, only 6,400 cached, 561 completion tokens. So caching helps a little but a conversation still costs ~35-40k tokens
against a 200k/day cap = about 5 conversations/day on the free plan. The full suite (14 cases x 3 runs = 42 conversations) does not fit.
Options: (a) Groq paid developer tier: this suite would cost cents; (b) another free provider (Gemini key) for the agent calls; (c) shrink the prompt.
Each transcript.json now records `usage`, so the cost of every run is visible.

## Cost levers (you chose: Gemini free key + shorter prompt)
- `agents/maya/v2` is a lean rewrite on `templates/prompt.md` (7.7k chars vs 27.5k). Measured: 17.6k prompt tokens per conversation vs 41k for v1 (-57%), booking flow still works.
  v2 is a DIFFERENT prompt from production: use it for cheap iteration, and run v1 (the real prompt) for results you report as "the agent". Any v1-vs-v2 gap is also a finding.
- Gemini: not set up yet, needs your key. Create one at aistudio.google.com, add `GEMINI_API_KEY` via the hidden-input command, then in `calleval.json` set `agent_llm` to
  `{"base_url":"https://generativelanguage.googleapis.com/v1beta/openai/","model":"<id from the models list>","key_env":"GEMINI_API_KEY"}` and tell me: I'll list the models and their limits.
  Use Gemini for the agent calls (the heavy ones); persona can stay on Groq.

## Findings about the Maya agent (from real runs, proxy model gpt-oss-20b, so confirm on the real agent)
- v1 and v2 both book without asking the caller's name: v1 used "Unknown"-style names ("John Doe"), v2 used the phone number as the name. Prompt says NEVER do this. -> case `asks-name-never-invents`.
- v2 booked Dr. Prasad at Koramangala on a Wednesday (he is Indiranagar-only on Wednesdays). -> case `maya-doctor-branch-schedule` (generated, Dr. Akram at Indiranagar).
- v1 prompt contradicts itself: "Transfer Call to a Human" says call the transfer tool when asked for a human, FAQ #8 says log the request and a manager will call back. v2 follows the transfer rule.
- v1 tells the model to "end the call using the end call tool" but the imported tool list has none; the proxy model invented `end_call_916372767324`. On the hosting platform the end-call tool is probably built in and invisible in the tool list.

## State
Built and self-checked WITHOUT any LLM key: import, mock tools, simulator, hard checks, judge protocol, report, versioning, 14 universal cases.
`python3 tests/test_loop.py` passes (fake LLMs drive the real loop). Smoke-tested on real Groq: one conversation end to end (import -> run -> judge -> report). Fixed along the way: persona emitting [END] on turn 1, persona writing several turns at once, agent calling a tool that doesn't exist (recorded as an agent failure).

## Morning checklist (needs you)
1. Make a free Groq key (console.groq.com), then `read -rs -p "Groq key: " K; echo; printf 'GROQ_API_KEY=%s\n' "$K" >> .env; unset K`
2. `./calleval.sh run --agent maya --cases relative-date-resolution --runs 1 --run-id smoke` (one conversation, ~50-70k tokens uncached).
3. Look at `runs/smoke/maya-v1/relative-date-resolution/1/transcript.json`. Does the agent call lookup_caller first and respect the tool schemas?
4. Check `https://console.groq.com/settings/limits` for YOUR free limits and whether prompt caching kicks in (the 2nd turn should be much cheaper).
5. Ask Claude Code to judge: "judge run smoke", then `./calleval.sh report smoke`.

## Research (sources read 2026-11-16)
- Groq limits page lists gpt-oss-120b/20b at 30 RPM, 1K RPD, 8K TPM, 200K TPD (page does not say which plan; the free plan has its own tab). The Maya prompt is ~7k tokens, so one uncached call nearly fills a minute and the day allows ~28 uncached calls. Groq docs say prompt caching is automatic for gpt-oss models, needs an exact prefix, and cached tokens do not count toward rate limits. Unverified on the free plan, so this is the first thing to test. The prompt is therefore always sent first, unchanged, as the system message.
  https://console.groq.com/docs/rate-limits , https://console.groq.com/docs/prompt-caching
- Gemini free tier: OpenAI-compatible endpoint `https://generativelanguage.googleapis.com/v1beta/openai/`, supports tool calling; free-tier token limits not retrieved. Cerebras: $5 trial credits, no permanent free tier. OpenRouter free models: 20 RPM, 50 requests/day (1000 after buying credits). Any of these works by editing `calleval.json` (base_url, model, key_env).
- Local Ollama is installed but this machine has no NVIDIA GPU and 15 GB RAM (11 in use): a 7k-token prompt on CPU would be too slow.
- Text mode re-runs the prompt + tools on a chosen model through the mock backend; a hosted platform's own chat endpoint is not used.
- ElevenLabs guidance turned into cases (each case's `source` field names the rule): confirm before state-changing tool calls, no guessing after tool failure / retry then escalate, speakable numbers and dates, guardrails (abuse, injection), concise replies, handoff triggers. ElevenLabs' own testing feature has three test types (simulation, next-reply, tool-call) and pass-rate colours (green 100%, amber >=80%): our design maps onto the same ideas. Language switching and turn-taking are not in their guide.

## Design decisions
- File contract: everything is plain files, so generator/judge/fixer can be Claude Code (subscription), an API model, or a human.
- Judge = Claude Code by default (independent of the Groq/OpenAI-family agent; costs no API tokens). `judge --llm` is a fallback.
- Precondition check: runs where the customer never did the scenario are VOID, not PASS.
- Hard checks (tool-call args by regex, "tool NOT called", forbidden agent text) are deterministic and override the judge.
- Status rule: hard fail = FAIL; judge fail in >=2 of >=3 valid runs = FAIL; 1 = FLAKY. Runs measure a rate, not existence; evidence quotes and a second look guard against false positives.
- Universal cases use `{task}`, `{book_tool}` etc. from agent.json `case_vars`; a case whose variable is undefined is skipped as not applicable.
- Versioning = git + `agents/<name>/vN/`. Held-out split so prompt fixes can't overfit the cases they were fixed on.

## Known gaps / next
- Text mode only; no audio, so no interruption, STT-noise, latency or TTS pronunciation tests. `audio.mp3` + turn `t` fields are already supported by the report for a future voice transport.
- Unverified: real-LLM behaviour (tool calling format on Groq, `reasoning_effort` param acceptance, caching).
- Judge not calibrated: hand-label ~10 transcripts and measure agreement before trusting pass rates.
- No platform importers (bring a prompt file and tools json instead) (each would be one small importer function).
- Persona may break character or finish early: the precondition/VOID mechanism is the guard; tune `PERSONA` in sim.py.
- Prompt-derived case generation and the improve loop are protocol in SKILL.md, not code (Claude Code does them).

## cmp run: v1 (production prompt) vs v2 (lean), Gemini agent, Groq persona, 1 run/case
- v1: 6/10 pass (fail: asks-name, language-switch-hindi, tool-failure-honesty; confirm-before-booking VOID, call ended before customer chose). 536k prompt tokens.
- v2: 9/11 pass (fail: confirm-before-booking, wrong-date-then-correct). 245k prompt tokens (~55% less).
- v2 weekday/date bug: called 2026-11-19 "Wednesday", booked 2026-11-20 for "Thursday". Fix idea: weekday->date table in prompt.
- v2 minor: booked as "Caller", asked consent after booking, said "transfer" without calling tool, 3 transfer calls with invented call_sid.
- Caveats: n=1 per case, proxy models, uncalibrated judge (verdicts by Claude Code), v2 != production prompt.
- Next: rerun failing cases with --runs 3 and more turns.

## Voice run vcmp: Maya v2 prompt, LiveKit twin, 11 train cases, 1 run each (2026-11-17)
Stack: Groq whisper-large-v3-turbo STT (English forced), Piper local TTS, Gemini 3.5 flash-lite for twin and persona, local livekit-server. Judged by Claude Code from judge_input.md (transcript + detector flags).
Result: 6 PASS / 4 FAIL / 1 VOID (human-handoff: caller asked once, not twice). Text run of the same prompt+cases (cmp) was 9/11, so voice exposes more.
- asks-name-never-invents FAIL: caller said "Neha Kapoor", agent STT heard "Ne Kippur", booked under it, never read the name back. Same class: "Arjun" -> "Origen", "Meera" -> "Mira" (other cases, not scored). Names garbled in 3 of 11 calls.
- tool-failure-honesty FAIL: one booking call errored, agent said "Let me try that again... is confirmed" without a second call. (In the text run this case passed: one run each is noise, use --runs 3.)
- language-switch-hindi FAIL, confounded: twin STT forced to English heard Hinglish as garbage; agent stayed English.
- maya-doctor-branch-schedule FAIL on a hard check: agent called check_availability for Dr. Akram at Indiranagar (tool call for a combination that cannot exist) though it told the caller the truth.
- Latency (end of caller speech -> agent speech): mostly 1.5-5s, worst 16s; this includes free-tier STT/LLM/TTS, not production latency.
- Brand names are consistently mis-transcribed by STT (Indiranagar, Koramangala, Syed) in both directions; the agent's own speech is also garbled by the persona's STT, so users with the same STT would hear/see the same errors.
- Detector precision so far: slow_response, agent_cut_off, STT mismatch useful; repeat fires on legitimate confirmations; dead_air counts model think time. Treat flags as hints.
- Worker jobs were refused at CPU load >0.7 (prod default): set load_threshold=0.95 and the runner retries a call once if a worker never starts.
Not yet done: ElevenLabs-derived pronunciation/normalization cases (dates, emails, IDs, amounts) as fixed voice tests; interruption tests where the persona deliberately talks over the agent; multiple runs per case; calibrate listening-model hints against human listening; other TTS/STT providers (ElevenLabs, Deepgram) behind the same adapters.
