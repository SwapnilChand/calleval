"""LiveKit worker. CALLEVAL_ROLE=twin|persona. Reads the spec path from the dispatch metadata, logs every event with wall time."""
import asyncio, json, os, sys, time
from pathlib import Path
from livekit import api, rtc
from livekit.agents import RoomInputOptions, RunContext, Agent, AgentServer, AgentSession, JobContext, cli, function_tool
from livekit.plugins import openai, silero

from calleval.core import load_env
load_env()
ROLE = os.environ.get("CALLEVAL_ROLE", "twin")
server = AgentServer(port=0, load_threshold=0.95)


def llm_of(c):
    key = os.environ.get(c.get("key_env") or "", "") or "none"            # local servers need no key
    return openai.LLM(model=c["model"], base_url=c["base_url"], api_key=key, temperature=c.get("temperature", 0.2),
                      **({"max_completion_tokens": c["max_tokens"]} if ROLE == "persona" and c.get("max_tokens") else {}))


@server.rtc_session(agent_name=ROLE)
async def entry(ctx: JobContext):
    spec = json.loads(Path(ctx.job.metadata).read_text())
    me, v = spec[ROLE], spec["voice"]
    log = open(Path(spec["run_dir"]) / f"events-{ROLE}.jsonl", "a", buffering=1)
    ev = lambda kind, **d: log.write(json.dumps({"t": time.time(), "role": ROLE, "kind": kind, **d}, ensure_ascii=False, default=str) + "\n")
    lk = api.LiveKitAPI(v["livekit_url"].replace("ws", "http", 1), v["api_key"], v["api_secret"])

    async def end_room(delay):
        await asyncio.sleep(delay)
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room=ctx.room.name))
        except Exception as e:
            ev("end_room_error", err=str(e))

    from calleval.voice.tools import build_tools
    ending = {"on": False}
    tools = build_tools(spec, ev, lambda: ending.update(on=True)) if ROLE == "twin" else []
    if ROLE == "persona":
        turns = []
        session_ref = {}

        @function_tool
        async def end_call(context: RunContext):
            """End the phone call after saying goodbye."""
            if sum(1 for _ in turns) < 3:          # same guard as the text runner: never hang up in the first 3 customer turns
                return "The call has barely started. Do not end it yet; continue the conversation."
            await context.wait_for_playout()
            ev("tool", name="end_call", args={}, result="ended")
            asyncio.create_task(end_room(1.5))
            return "ok"
        tools = [end_call]

    from calleval.voice.tts import GeminiTTS, PiperTTS
    from calleval.core import ROOT
    if v["tts"] == "piper":
        tts = PiperTTS(ROOT / ".tools" / "voices" / (v[ROLE + "_voice"] + ".onnx"))
    else:                                          # gemini: free tier is ~10 requests/minute/model, whole turn per request
        g = v["gemini"]
        tts = GeminiTTS(g[ROLE + "_model"], g[ROLE + "_voice"], os.environ["GEMINI_API_KEY"])
        from livekit.agents import tokenize, tts as lktts
        tts = lktts.StreamAdapter(tts=tts, sentence_tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=400))
    if v["stt"] == "local":
        from calleval.voice.stt import LocalWhisperSTT
        stt_ = LocalWhisperSTT(v["stt_model"])
    elif v["stt"] == "groq":
        from livekit.plugins import groq
        stt_ = groq.STT(model=v["stt_model"], api_key=os.environ[v.get("stt_key_env", "GROQ_API_KEY")], language="en")
    else:                                          # any OpenAI-compatible transcription endpoint
        stt_ = openai.STT(model=v["stt_model"], base_url=v["stt_base_url"], api_key=os.environ.get(v.get("stt_key_env", ""), "none"), language="en")
    session = AgentSession(stt=stt_,
                           llm=llm_of(me["llm"]), tts=tts, vad=silero.VAD.load())
    if ROLE == "persona":
        session.on("conversation_item_added", lambda e: getattr(e.item, "type", "") == "message" and e.item.role == "assistant" and turns.append(1))
    session.on("user_state_changed", lambda e: ev("user_state", new=e.new_state))
    def on_agent_state(e):
        ev("agent_state", new=e.new_state)
        if ending["on"] and e.new_state == "listening":      # end/transfer tool ran and the agent finished speaking its closing line
            ending["on"] = False
            asyncio.create_task(end_room(1.5))
    session.on("agent_state_changed", on_agent_state)
    session.on("user_input_transcribed", lambda e: ev("heard", text=e.transcript, final=e.is_final))
    session.on("conversation_item_added", lambda e: getattr(e.item, "type", "") == "message" and ev("said", item_role=e.item.role, text=e.item.text_content, created=e.item.created_at, interrupted=getattr(e.item, "interrupted", False)))
    session.on("metrics_collected", lambda e: ev("metrics", m=e.metrics.model_dump() if hasattr(e.metrics, "model_dump") else str(e.metrics)))
    session.on("close", lambda e: ev("close", reason=str(getattr(e, "reason", ""))))

    await session.start(agent=Agent(instructions=me["prompt"], tools=tools), room=ctx.room,
                        room_input_options=RoomInputOptions(participant_kinds=[rtc.ParticipantKind.PARTICIPANT_KIND_AGENT]))
    ev("ready")
    if ROLE == "twin":
        await session.say(me["welcome"], allow_interruptions=True)


if __name__ == "__main__":
    cli.run_app(server)
