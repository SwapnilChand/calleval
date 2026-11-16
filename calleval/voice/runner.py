"""Voice run: local LiveKit server + twin worker + persona worker; per call: room, recorder, transcript.json (same shape as text runs)."""
import asyncio, json, os, re, subprocess, sys, time, wave
from pathlib import Path
from livekit import api, rtc
from ..core import ROOT, load_env

SR = 24000
TOOLS = ROOT / ".tools"


def wait_for(fn, timeout, what):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if fn():
            return
        time.sleep(0.5)
    raise SystemExit(f"timed out waiting for {what}")


class Stack:
    """Starts and stops livekit-server and the two workers."""
    def __init__(self, v, logdir):
        self.v, self.logdir, self.procs = v, Path(logdir), []
        self.logdir.mkdir(parents=True, exist_ok=True)

    def start(self):
        v = self.v
        env = {**os.environ, "LIVEKIT_URL": v["livekit_url"], "LIVEKIT_API_KEY": v["api_key"],
               "LIVEKIT_API_SECRET": v["api_secret"], "PYTHONPATH": str(ROOT)}
        srv = subprocess.Popen([str(TOOLS / "livekit-server"), "--dev", "--keys", f"{v['api_key']}: {v['api_secret']}"],
                               stdout=open(self.logdir / "server.log", "w"), stderr=subprocess.STDOUT)
        self.procs.append(srv)
        import urllib.request
        def up():
            try:
                urllib.request.urlopen(v["livekit_url"].replace("ws", "http", 1), timeout=1)
                return True
            except Exception as e:
                return getattr(e, "code", 0) in (200, 404, 405)
        wait_for(up, 20, "livekit-server")
        for role in ("persona", "twin"):
            log = self.logdir / f"worker-{role}.log"
            self.procs.append(subprocess.Popen([sys.executable, "-m", "calleval.voice.worker", "start"],
                env={**env, "CALLEVAL_ROLE": role}, stdout=open(log, "w"), stderr=subprocess.STDOUT, cwd=ROOT))
            wait_for(lambda: "registered worker" in log.read_text(), 90, f"{role} worker")

    def stop(self):
        for p in reversed(self.procs):
            p.terminate()
        for p in self.procs:
            try:
                p.wait(10)
            except Exception:
                p.kill()


async def record(v, room_name, chunks, stop):
    tok = (api.AccessToken(v["api_key"], v["api_secret"]).with_identity("recorder").with_grants(
        api.VideoGrants(room_join=True, room=room_name, can_publish=False, hidden=True)).to_jwt())
    room = rtc.Room()
    tasks = []

    async def rec(track, ident):
        async for e in rtc.AudioStream(track, sample_rate=SR, num_channels=1):
            chunks.setdefault(ident, []).append((time.time(), bytes(e.frame.data)))

    @room.on("track_subscribed")
    def _(track, pub, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            tasks.append(asyncio.create_task(rec(track, participant.identity)))
    await room.connect(v["livekit_url"], tok)
    await stop.wait()
    await room.disconnect()


def write_wavs(chunks, t0, outdir, names):
    """Aligned mono wav per speaker (silence between frames) + a stereo mix L=agent R=customer."""
    paths, data = {}, {}
    for ident, fr in chunks.items():
        buf, pos = bytearray(), 0
        for t, b in fr:
            want = max(pos, int((t - t0) * SR) * 2)
            buf += b"\0" * (want - pos) + b
            pos = want + len(b)
        data[ident] = bytes(buf)
    for ident, b in data.items():
        name = names.get(ident, ident)
        p = outdir / f"{name}.wav"
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(b)
        paths[name] = p
    if len(paths) == 2:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(paths["agent"]), "-i", str(paths["customer"]),
                        "-filter_complex", "[0:a][1:a]amerge=inputs=2[a]", "-map", "[a]", "-b:a", "64k", str(outdir / "audio.mp3")])
    return paths


def read_events(d):
    out = []
    for r in ("twin", "persona"):
        f = d / f"events-{r}.jsonl"
        if f.exists():
            out += [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
    return sorted(out, key=lambda e: e["t"])


def to_transcript(d, spec, t0):
    ev = read_events(d)
    said = [e for e in ev if e["kind"] == "said" and e["item_role"] == "assistant" and e["text"]]
    said.sort(key=lambda e: e.get("created", e["t"]))
    turns = [{"i": i, "role": "agent" if e["role"] == "twin" else "customer", "text": e["text"].strip(),
              "t": round(e.get("created", e["t"]) - t0, 2), "interrupted": e["interrupted"]} for i, e in enumerate(said)]
    calls = []
    for e in ev:
        if e["kind"] == "tool" and e["role"] == "twin":
            # a tool belongs to the agent reply that follows it (same numbering as text runs)
            k = next((i for i, s_ in enumerate(said) if s_["role"] == "twin" and s_.get("created", s_["t"]) > e["t"]), max(len(turns) - 1, 0))
            calls.append({"turn": k, "name": e["name"], "args": e["args"], "result": e["result"], "t": round(e["t"] - t0, 2)})
            if turns:
                turns[k].setdefault("tools", []).append(e["name"])
    heard = [{"by": "agent" if e["role"] == "twin" else "customer", "t": round(e["t"] - t0, 2), "text": e["text"].strip()}
             for e in ev if e["kind"] == "heard" and e["final"]]
    return turns, calls, heard


async def one_call(v, spec_path, spec, d):
    for attempt in (1, 2):
        for f in d.glob("events-*.jsonl"):
            f.unlink()
        res = await _one_call(v, spec_path, spec, d)
        if not (res["ended"] == "error" or (res["ended"] == "max_seconds" and not res["turns"])):
            break
    res["attempts"] = attempt
    return res


async def _one_call(v, spec_path, spec, d):
    lk = api.LiveKitAPI(v["livekit_url"].replace("ws", "http", 1), v["api_key"], v["api_secret"])
    name = "call-" + d.parent.name + "-" + d.name + "-" + str(int(time.time()))
    await lk.room.create_room(api.CreateRoomRequest(name=name, empty_timeout=30))
    chunks, stop = {}, asyncio.Event()
    rec = asyncio.create_task(record(v, name, chunks, stop))
    await asyncio.sleep(2)
    t0 = time.time()
    dispatch = lambda who: lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(agent_name=who, room=name, metadata=str(spec_path)))
    await dispatch("persona")
    for _ in range(90):
        if (d / "events-persona.jsonl").exists() and '"ready"' in (d / "events-persona.jsonl").read_text():
            break
        await asyncio.sleep(0.5)
    if '"ready"' not in (d / "events-persona.jsonl").read_text() if (d / "events-persona.jsonl").exists() else True:
        await lk.room.delete_room(api.DeleteRoomRequest(room=name)); stop.set(); await rec; await lk.aclose()
        return {"turns": [], "tool_calls": [], "ended": "error", "error": "persona worker never became ready (see _stack/worker-persona.log)", "usage": {}}
    t_twin = time.time()
    await dispatch("twin")
    for _ in range(90):
        if (d / "events-twin.jsonl").exists() and '"ready"' in (d / "events-twin.jsonl").read_text():
            break
        await asyncio.sleep(0.5)
    else:
        await lk.room.delete_room(api.DeleteRoomRequest(room=name)); stop.set(); await rec; await lk.aclose()
        return {"turns": [], "tool_calls": [], "ended": "error", "error": "twin worker never became ready (see _stack/worker-twin.log)", "usage": {}}
    ended = "max_seconds"
    while time.time() - t_twin < spec["max_seconds"]:
        await asyncio.sleep(1)
        rooms = (await lk.room.list_rooms(api.ListRoomsRequest(names=[name]))).rooms
        if not rooms:
            ended = "room_closed"
            break
    if ended == "max_seconds":
        await lk.room.delete_room(api.DeleteRoomRequest(room=name))
    await asyncio.sleep(1.5)
    stop.set(); await rec
    await lk.aclose()
    order = list(chunks)                                           # the twin greets first, so its audio arrives first
    names = {order[0]: "agent", order[1]: "customer"} if len(order) == 2 else {}
    write_wavs(chunks, t0, d, names)
    turns, calls, heard = to_transcript(d, spec, t0)
    (d / "transcript.json").write_text(json.dumps({"case": spec["case"], "turns": turns, "tool_calls": calls, "heard": heard}))   # analyze reads it
    from .analyze import analyze, spoken_forms
    an = analyze(d, t0)
    if os.environ.get("GEMINI_API_KEY") and (d / "agent.wav").exists() and any(re.search(r"\d", x["text"]) for x in turns if x["role"] == "agent"):
        try:
            an["spoken_forms"] = spoken_forms(d / "agent.wav", os.environ["GEMINI_API_KEY"])
        except Exception as e:
            an["spoken_forms_error"] = str(e)[:120]
    (d / "analysis.json").write_text(json.dumps(an, indent=1, ensure_ascii=False))
    return {"turns": turns, "tool_calls": calls, "heard": heard, "ended": ended, "error": None, "usage": {}, "t0": t0, "analysis": an}
