"""Provider adapter: Bolna's streaming web-call socket (JSON over WebSocket, 16 kHz mono PCM16, base64) plus its REST records.
Adapter interface (any provider can implement it): connect(session) -> ws, packets(ws) -> async iterator of ("audio", pcm) | ("clear",) | ("mark", msg),
send_audio(ws, pcm), send_json(ws, msg), balance(), find_execution(since_epoch)."""
import asyncio, base64, json, os, time, urllib.request
import aiohttp

NAME = "bolna"


class Adapter:
    def __init__(self, agent_id, key=None, host=None, api=None):
        self.agent_id, self.key = agent_id, key or os.environ["BOLNA_API_KEY"]
        self.host = (host or os.environ.get("BOLNA_WS_HOST") or "wss://api.bolna.ai").rstrip("/")
        self.api = (api or os.environ.get("BOLNA_API_BASE") or "https://api.bolna.ai").rstrip("/")

    async def connect(self, session):
        url = f"{self.host}/web-call/v1/{self.agent_id}?auth_token={self.key}&user_agent=web-call&enforce_streaming=true"
        ws = await session.ws_connect(url, timeout=aiohttp.ClientWSTimeout(ws_close=20))
        await ws.send_json({"type": "init", "meta_data": {"context_data": {}}})
        return ws

    async def packets(self, ws):
        async for m in ws:
            if m.type != aiohttp.WSMsgType.TEXT:
                continue
            d = json.loads(m.data)
            k = d.get("type")
            if k == "audio":
                yield ("audio", base64.b64decode(d["data"]))
            elif k in ("clear", "mark", "ack"):
                yield (k, d)

    async def send_audio(self, ws, pcm):
        await ws.send_json({"type": "audio", "data": base64.b64encode(pcm).decode()})

    def _get(self, path):
        r = urllib.request.Request(self.api + path, headers={"Authorization": "Bearer " + self.key, "User-Agent": "calleval"})
        return json.load(urllib.request.urlopen(r, timeout=30))

    def balance(self):
        try:
            return float(self._get("/user/me")["wallet"])
        except Exception:
            return None

    def find_execution(self, since_epoch, wait=60):
        """The finished record of the call we just made (transcript, cost, latency data)."""
        end = time.time() + wait
        while time.time() < end:
            try:
                rows = self._get(f"/v2/agent/{self.agent_id}/executions?page_size=5").get("data", [])
                for r in rows:
                    ts = time.mktime(time.strptime(r["created_at"][:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
                    if ts >= since_epoch - 30 and r.get("status") == "completed":
                        return r
            except Exception:
                pass
            time.sleep(4)
        return None
