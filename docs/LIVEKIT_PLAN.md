# Voice runs on LiveKit (local, no phone numbers)
Sources: docs.livekit.io (testing/simulations.md, testing/debugger.md, llms.txt), livekit.io/pricing.md. Not yet installed or run.

## What LiveKit already offers
- Agents framework (Apache-2.0, free, Python). Open-source server can be self-hosted. Two participants in one room = no phone numbers.
- `lk agent debugger` (local, free besides your own LLM calls): a script or Claude Code acts as the user, one turn at a time, text by default, `--audio` to speak each turn (shows STT mishearings, digits-as-words, turns cut early).
- Agent Simulations (text + audio, LLM simulated user + LLM judge): runs on LiveKit Cloud only, needs a Cloud project, scenario generation uploads agent source. Free Build plan: 350 text turns, 60 audio turns; then $0.02 / $0.05 per turn.
- Egress recording (own storage), data hooks (transcripts, metrics), OpenTelemetry traces.

## What it does NOT do for us
It runs a rebuilt "voice twin" of the customer's agent (their prompt + tools on our chosen STT/LLM/TTS), not the hosting platform's real pipeline. Voice results are valid for the services chosen.

## Options
A. Use LiveKit's hosted simulations: least work, but Cloud-only, small free quota, overlaps with calleval itself.
B. Debugger audio mode driven by calleval (persona = our LLM, Claude Code optional): local, free, partial audio data.
C. Own runner: local livekit-server + two agents in a room (agent twin + persona bot), egress per-track recording, our detectors/judge/report. Most work, platform-neutral, free, exact per-speaker timing.
Plan: B first to prove the twin, then C.

## Customer onboarding story
1. skill/CLI: bring a prompt file (+ optional tools json) with `new-agent`, or start from the template.
2. generate the voice twin (agent.py from agents/<name>/vN: prompt, tools, mock backend).
3. pick voice stack (free default) and keys in .env.
4. text run (cheap) -> audio run -> detectors -> judge -> HTML report with audio per turn.

## Built (2026-11-17)
- `calleval/voice/`: spec.py (one spec.json per call), worker.py (twin|persona LiveKit workers), tools.py (raw-schema tools on the mock backend), tts.py (Piper local, Gemini REST), runner.py (server + workers + room + per-speaker recorder), analyze.py (detectors), debug_agent.py (option B).
- Commands: `voice-run` (option C), `twin-debug` + `lk agent debugger` (option B, text mode).
- Free stack that works: Groq whisper-large-v3-turbo STT, Piper TTS (local), Gemini flash-lite LLM for twin and persona, livekit-server --dev, ffmpeg for mp3.

## Findings while building
- livekit google plugin's Gemini TTS request is rejected by the API (400 speechConfig); we use our own REST adapter. Gemini TTS free tier: ~10 requests/minute/model (429 after that) -> default to Piper.
- Agent-to-agent in one room: sessions only link to AGENT-kind participants if `RoomInputOptions(participant_kinds=[AGENT])`; the default accepts only human/phone kinds.
- `function_tool` needs a `RunContext` type hint on the context parameter or it becomes a model-visible argument; raw handlers need `raw_arguments: dict[str, object]`.
- Whisper formats digits itself ("2026-121"), hiding the spoken form; a listening model asked for a verbatim word transcript showed Gemini TTS saying "two zero two six, eleven two one" for 2026-11-21.
- Persona model writing several turns in one message breaks voice calls even more than text; fixed by a short-reply model with a token cap, and an end_call guard (not before 3 customer turns).
- `lk agent debugger`: text mode free; audio mode bills LiveKit Cloud inference, so our own runner is the audio path.
- Test-infra latency: persona/twin STT+LLM+TTS on free tiers gives 1.5-5s response latency; treat as stack latency, not production.
