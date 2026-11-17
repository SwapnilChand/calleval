"""Live run: our customer bot talks to a hosted agent over its streaming socket, in real time. Local STT (faster-whisper) hears the agent,
the persona model decides what to say, local TTS (Piper) speaks it. Records both sides and a timeline, then adds the provider's own record."""
import asyncio, json, re, subprocess, time, wave
from pathlib import Path
import aiohttp, numpy as np
from ..core import ROOT
from ..llm import chat
from ..sim import PERSONA

RATE, TICK = 16000, 0.1
STEP = int(2 * RATE * TICK)


class Voice:
    """Local speech models, loaded once."""
    def __init__(self, cfg):
        from faster_whisper import WhisperModel
        from piper import PiperVoice
        v = cfg["voice"]
        self.stt = WhisperModel(v.get("stt_model", "base.en") if v.get("stt") == "local" else "base.en", device="cpu", compute_type="int8", cpu_threads=4)
        self.tts = PiperVoice.load(str(ROOT / ".tools" / "voices" / (v["persona_voice"] + ".onnx")))

    def hear(self, pcm):
        a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segs, _ = self.stt.transcribe(a, language="en", beam_size=1)
        return " ".join(s.text.strip() for s in segs).strip()

    def say(self, text):
        raw = b"".join(c.audio_int16_bytes for c in self.tts.synthesize(text))
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        n = int(len(a) * RATE / self.tts.config.sample_rate)
        return np.interp(np.linspace(0, max(len(a) - 1, 0), n), np.arange(len(a)), a).astype(np.int16).tobytes()


class Track:
    def __init__(self):
        self.parts = []

    def add(self, off, pcm):
        self.parts.append((off, pcm))

    def wav(self, path, total):
        buf = np.zeros(int(total * RATE) + RATE, dtype=np.int32)
        for off, pcm in self.parts:
            a = np.frombuffer(pcm, dtype=np.int16).astype(np.int32)
            i = int(off * RATE)
            buf[i:i + len(a)] += a[: max(0, len(buf) - i)]
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
            w.writeframes(np.clip(buf, -32768, 32767).astype(np.int16).tobytes())


def persona_line(cfg, persona_system, turns, n_customer):
    msgs = [{"role": "system", "content": persona_system}] + [
        {"role": "user" if x["role"] == "agent" else "assistant", "content": x["text"]} for x in turns]
    m, _ = chat(cfg["persona_llm"], msgs)
    text = (m.get("content") or "").strip().replace("\n", " ")
    asked = bool(turns) and turns[-1]["role"] == "agent" and turns[-1]["text"].rstrip().endswith("?")      # nobody hangs up while a question is open
    end = "[END]" in text and n_customer >= 3 and not asked
    text = text.replace("[END]", "").strip()
    sents = re.split(r"(?<=[.?!])\s+", text)
    return " ".join(sents[:2]).strip() or "Okay.", end


async def converse(adp, voice, cfg, persona_system, max_turns, max_seconds, log=print):
    t0 = time.time()
    now = lambda: time.time() - t0
    agent_tr, cust_tr = Track(), Track()
    ev, turns = [], []
    S = {"play_end": 0.0, "last_pkt": 0.0, "pcm": [], "start": None, "interrupted": False, "pending": b"", "closed": False, "sent_until": 0.0}
    ended = "max_seconds"

    async with aiohttp.ClientSession() as http:
        ws = await adp.connect(http)

        async def reader():
            async for kind, d in adp.packets(ws):
                t = now()
                if kind == "audio":
                    d = d[: len(d) // 2 * 2]                      # providers send stray 1-byte packets after markers
                    if not d:
                        continue
                    start = max(t, S["play_end"])
                    if S["start"] is None:
                        S["start"] = start; ev.append((start, "agent_state", "speaking"))
                    S["pcm"].append((start, d))
                    S["play_end"] = start + len(d) / (2 * RATE)
                    S["last_pkt"] = t
                    agent_tr.add(start, d)
                elif kind == "mark":
                    asyncio.get_running_loop().call_later(max(0.0, S["play_end"] - t), lambda m=d: asyncio.create_task(ws.send_json(m)))
                elif kind == "clear":
                    # the provider sends `clear` whenever the caller starts speaking; it is only a cut-off if the agent was still talking
                    if S["start"] is not None and t < S["play_end"] - 0.2:
                        S["interrupted"] = True
                        S["play_end"] = t
            S["closed"] = True

        async def sender():
            speaking = False
            while not S["closed"]:
                if S["pending"]:
                    chunk, S["pending"] = S["pending"][:STEP], S["pending"][STEP:]
                    chunk = chunk.ljust(STEP, b"\0")
                    if not speaking:
                        speaking = True; ev.append((now(), "user_state", "speaking")); S["spk_start"] = now()
                    cust_tr.add(now(), chunk)
                else:
                    chunk = bytes(STEP)
                    if speaking:
                        speaking = False; ev.append((now(), "user_state", "listening"))
                try:
                    await adp.send_audio(ws, chunk)
                except Exception:
                    break
                await asyncio.sleep(TICK)

        rt, st = asyncio.create_task(reader()), asyncio.create_task(sender())

        async def next_agent_turn(timeout):
            """Wait for the agent to start and finish speaking; returns (text, start, end, interrupted) or None."""
            end_by = now() + timeout
            while now() < end_by and not S["closed"]:
                if S["start"] is not None and now() > S["play_end"] + 1.0 and now() - S["last_pkt"] > 1.0:
                    pcm = b"".join(p for _, p in S["pcm"])
                    start, end, intr = S["start"], S["play_end"], S["interrupted"]
                    ev.append((end, "agent_state", "listening"))
                    S.update(pcm=[], start=None, interrupted=False)
                    text = await asyncio.to_thread(voice.hear, pcm)
                    return text, start, end, intr
                await asyncio.sleep(0.1)
            return None

        try:
            n_cust = 0
            while now() < max_seconds and not S["closed"]:
                a = await next_agent_turn(25 if turns else 20)
                if a is None:
                    ended = "agent_hangup" if S["closed"] else "agent_silent"; break
                text, start, end, intr = a
                if text:
                    turns.append({"i": len(turns), "role": "agent", "text": text, "t": round(start, 2), "interrupted": intr})
                    log(f"    agent: {text[:90]}")
                if n_cust >= max_turns:
                    ended = "max_turns"; break
                line, finish = await asyncio.to_thread(persona_line, cfg, persona_system, turns, n_cust)
                pcm = await asyncio.to_thread(voice.say, line)
                turns.append({"i": len(turns), "role": "customer", "text": line, "t": round(now(), 2)}); n_cust += 1
                log(f"    customer: {line[:90]}")
                S["pending"] += pcm
                while S["pending"] and not S["closed"]:
                    await asyncio.sleep(0.1)
                if finish:
                    last = await next_agent_turn(8)
                    if last and last[0]:
                        turns.append({"i": len(turns), "role": "agent", "text": last[0], "t": round(last[1], 2), "interrupted": last[3]})
                    ended = "customer_end"; break
            else:
                ended = "agent_hangup" if S["closed"] else "max_seconds"
        finally:
            st.cancel(); await ws.close(); rt.cancel()
    return {"turns": turns, "events": ev, "agent_track": agent_tr, "cust_track": cust_tr, "ended": ended, "t0": t0, "dur": now()}


def parse_platform(transcript):
    out = []
    for line in (transcript or "").splitlines():
        m = re.match(r"\s*(assistant|user):\s*(.*)", line)
        if m:
            out.append({"role": "agent" if m.group(1) == "assistant" else "customer", "text": m.group(2).strip()})
    return out


def write_run(d, res, rec, case, meta):
    """Write the same files a voice run writes (+ the provider's own record) so judge, analysis and report work unchanged."""
    d.mkdir(parents=True, exist_ok=True)
    total = res["dur"]
    res["agent_track"].wav(d / "agent.wav", total); res["cust_track"].wav(d / "customer.wav", total)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(d / "agent.wav"), "-i", str(d / "customer.wav"),
                    "-filter_complex", "[0:a][1:a]amerge=inputs=2[a]", "-map", "[a]", "-b:a", "64k", str(d / "audio.mp3")])
    t0 = res["t0"]
    # timeline in the same event format the voice analysis reads (the "twin" side = the agent)
    (d / "events-twin.jsonl").write_text("\n".join(json.dumps({"t": t0 + t, "role": "twin", "kind": k, "new": v}) for t, k, v in sorted(res["events"])))
    platform = parse_platform((rec or {}).get("transcript"))
    heard = []                                   # what the agent's own speech-to-text wrote for each customer line
    cust_turns = [x for x in res["turns"] if x["role"] == "customer"]
    for x, p in zip(cust_turns, [p for p in platform if p["role"] == "customer"]):
        heard.append({"by": "agent", "t": x["t"] + 1.0, "text": p["text"]})
    for x in res["turns"]:
        if x["role"] == "agent":
            heard.append({"by": "customer", "t": x["t"] + 0.1, "text": x["text"]})
    tr = {"agent": meta["agent"], "version": meta["version"], "run": meta["run"], "case": case, "mode": "live", "live": True,
          "turns": res["turns"], "tool_calls": [], "heard": heard, "ended": res["ended"], "error": None, "usage": {}, "t0": t0,
          "platform": {"provider": meta["provider"], "transcript": platform, "cost": (rec or {}).get("total_cost"),
                       "duration": ((rec or {}).get("telephony_data") or {}).get("duration"), "latency": (rec or {}).get("latency_data"),
                       "execution_id": (rec or {}).get("id")}}
    (d / "transcript.json").write_text(json.dumps(tr, indent=1, ensure_ascii=False))
    from ..voice.analyze import analyze
    an = analyze(d, t0)
    (d / "analysis.json").write_text(json.dumps(an, indent=1, ensure_ascii=False))
    tr["analysis"] = an
    (d / "transcript.json").write_text(json.dumps(tr, indent=1, ensure_ascii=False))
    return tr
