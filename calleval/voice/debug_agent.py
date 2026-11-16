"""Entrypoint for `lk agent debugger start calleval/voice/debug_agent.py` (text mode: free; Claude Code or a script plays the caller).
Reads CALLEVAL_SPEC (spec.json from `calleval twin-debug`)."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli
from livekit.agents.llm import ChatContext
from livekit.plugins import openai
from calleval.core import load_env
from calleval.voice.tools import build_tools

load_env()
server = AgentServer()


@server.rtc_session()
async def entry(ctx: JobContext):
    spec = json.loads(Path(os.environ["CALLEVAL_SPEC"]).read_text())
    me, c = spec["twin"], spec["twin"]["llm"]
    ctx_ = ChatContext.empty()
    ctx_.add_message(role="assistant", content=me["welcome"])
    session = AgentSession(llm=openai.LLM(model=c["model"], base_url=c["base_url"], api_key=os.environ[c["key_env"]], temperature=c.get("temperature", 0.2)))
    await session.start(agent=Agent(instructions=me["prompt"], tools=build_tools(spec), chat_ctx=ctx_), room=ctx.room)


if __name__ == "__main__":
    cli.run_app(server)
