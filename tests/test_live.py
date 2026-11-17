"""Live-run check against a FAKE streaming agent (same wire protocol, local, free). Needs the voice pieces: `.venv/bin/python tests/test_live.py`."""
import asyncio, base64, datetime as dt, json, os, shutil, sys, tempfile, threading
from pathlib import Path
REAL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REAL))
from aiohttp import web
import numpy as np
from piper import PiperVoice
from calleval import cli, core, llm

voice = PiperVoice.load(str(REAL / ".tools/voices/en_US-lessac-medium.onnx"))
def tts(text):
    raw = b"".join(c.audio_int16_bytes for c in voice.synthesize(text)); a = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    n = int(len(a) * 16000 / voice.config.sample_rate)
    return np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.int16).tobytes()
REPLIES = ["Hi, this is Maya from the clinic. How can I help you?", "Sure. Which doctor would you like to see?", "Your appointment is booked. Anything else?", "Goodbye."]

async def ws_handler(req):
    ws = web.WebSocketResponse(); await ws.prepare(req)
    assert (await ws.receive_json())["type"] == "init"
    await ws.send_json({"type": "ack"})
    async def say(text):
        pcm = tts(text)
        for i in range(0, len(pcm), 64000):
            await ws.send_json({"type": "audio", "data": base64.b64encode(pcm[i:i + 64000]).decode()})
        await ws.send_json({"type": "mark", "name": "m"})
        await ws.send_json({"type": "audio", "data": base64.b64encode(b"\x00").decode()})      # real providers send a stray 1-byte packet
    await say(REPLIES[0]); n, speech, quiet = 1, 0.0, 0.0
    async for m in ws:
        if m.type != web.WSMsgType.TEXT: continue
        d = json.loads(m.data)
        if d["type"] != "audio": continue
        a = np.frombuffer(base64.b64decode(d["data"]), dtype=np.int16)
        if np.abs(a).mean() > 300:
            if speech == 0.0: await ws.send_json({"type": "clear", "data": None})       # providers clear their queue when the caller starts talking
            speech += 0.1; quiet = 0.0
        else:
            quiet += 0.1
            if speech > 0.5 and quiet >= 1.3:
                speech = 0.0
                if n < len(REPLIES):
                    await say(REPLIES[n]); n += 1
                if n >= len(REPLIES):
                    await asyncio.sleep(2); await ws.close(); break
    return ws

async def me(req): return web.json_response({"wallet": 100.0})
async def execs(req):
    return web.json_response({"data": [{"id": "x1", "status": "completed", "created_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "+00:00",
        "total_cost": "1.5", "transcript": "assistant: " + REPLIES[0] + "\nuser: I want to book tomorrow\nassistant: " + REPLIES[1], "telephony_data": {"duration": 20.0},
        "latency_data": {"time_to_first_audio": 0.8, "interruption_stats": {}}}]})

def serve(port, ready):
    async def run():
        app = web.Application(); app.router.add_get("/web-call/v1/{agent}", ws_handler); app.router.add_get("/user/me", me); app.router.add_get("/v2/agent/{a}/executions", execs)
        r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", port).start(); ready.set(); await asyncio.sleep(600)
    asyncio.run(run())
ready = threading.Event(); threading.Thread(target=serve, args=(8799, ready), daemon=True).start(); ready.wait(10)
os.environ.update(BOLNA_API_KEY="k", BOLNA_WS_HOST="ws://127.0.0.1:8799", BOLNA_API_BASE="http://127.0.0.1:8799")

lines = ["I want to book an appointment tomorrow at ten.", "Dr. Prasad please.", "Great, thanks. Goodbye. [END]"]; k = {"n": 0}
def persona(msgs, tools): k["n"] += 1; return {"content": lines[min(k["n"] - 1, 2)]}
llm.FAKES["persona"] = persona
cfg = lambda: {**core.DEFAULTS, "persona_llm": {"base_url": "fake:persona"}, "turns": 4, "runs": 1}
root = Path(tempfile.mkdtemp()); core.load_config = cli.load_config = cfg; core.ROOT = cli.ROOT = root
shutil.copytree(REAL / "agents", root / "agents"); shutil.copytree(REAL / "cases", root / "cases"); os.symlink(REAL / ".tools", root / ".tools")
cli.main(["live-run", "--agent", "maya", "--version", "v2", "--cases", "relative-date-resolution", "--provider-agent-id", "abc12345-0000", "--real-tools", "--run-id", "lv"])
d = root / "runs/lv/maya-v2/relative-date-resolution/1"
t = json.loads((d / "transcript.json").read_text())
assert t["live"] and sum(x["role"] == "agent" for x in t["turns"]) >= 2 and sum(x["role"] == "customer" for x in t["turns"]) >= 2, t["turns"]
assert not any(x.get("interrupted") for x in t["turns"]), "a clear signal after the agent finished must not count as a cut-off"
assert t["platform"]["cost"] == "1.5" and (d / "audio.mp3").stat().st_size > 1000 and "latency_s" in t["analysis"]
assert "Provider record" in (lambda: (cli.main(["judge", "lv"]), (d / "judge_input.md").read_text())[1])()
cli.main(["report", "lv"])
assert (root / "runs/lv/report.html").stat().st_size > 1000
print("OK", [(x["role"][0], x["text"][:30]) for x in t["turns"]])
