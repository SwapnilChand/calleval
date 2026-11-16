"""Gemini TTS over plain REST (the livekit google plugin's request shape is rejected by the API, checked 2026-11-17)."""
import asyncio, base64, io, json, time, urllib.error, urllib.request, wave
from livekit.agents import tts, utils
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

SR = 24000


def synth(model, voice, key, text):
    body = {"contents": [{"parts": [{"text": text}]}], "generationConfig": {"responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                 json.dumps(body).encode(), {"x-goog-api-key": key, "Content-Type": "application/json"})
    for attempt in range(5):                       # free tier = ~10 requests/minute per model
        try:
            p = json.load(urllib.request.urlopen(req, timeout=60))["candidates"][0]["content"]["parts"][0]["inlineData"]
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 4:
                raise
            time.sleep(8)
    raw = base64.b64decode(p["data"])
    if p["mimeType"].startswith("audio/wav"):
        with wave.open(io.BytesIO(raw)) as w:
            return w.readframes(w.getnframes()), w.getframerate()
    return raw, SR


class GeminiTTS(tts.TTS):
    def __init__(self, model, voice, api_key):
        super().__init__(capabilities=tts.TTSCapabilities(streaming=False), sample_rate=SR, num_channels=1)
        self._m, self._v, self._k = model, voice, api_key

    def synthesize(self, text, *, conn_options=DEFAULT_API_CONNECT_OPTIONS):
        return _Stream(tts=self, input_text=text, conn_options=conn_options)


class _Stream(tts.ChunkedStream):
    async def _run(self, out):
        t = self._tts
        pcm, rate = await asyncio.to_thread(synth, t._m, t._v, t._k, self._input_text)
        out.initialize(request_id=utils.shortuuid(), sample_rate=rate, num_channels=1, mime_type="audio/pcm")
        out.push(pcm)
        out.flush()


class PiperTTS(tts.TTS):
    """Local, free, no quota (piper-tts is GPL-3.0: optional extra, not bundled)."""
    def __init__(self, onnx_path):
        from piper import PiperVoice
        self._voice = PiperVoice.load(str(onnx_path))
        super().__init__(capabilities=tts.TTSCapabilities(streaming=False), sample_rate=self._voice.config.sample_rate, num_channels=1)

    def synthesize(self, text, *, conn_options=DEFAULT_API_CONNECT_OPTIONS):
        return _PiperStream(tts=self, input_text=text, conn_options=conn_options)


class _PiperStream(tts.ChunkedStream):
    async def _run(self, out):
        v = self._tts._voice
        pcm = await asyncio.to_thread(lambda: b"".join(c.audio_int16_bytes for c in v.synthesize(self._input_text)))
        out.initialize(request_id=utils.shortuuid(), sample_rate=v.config.sample_rate, num_channels=1, mime_type="audio/pcm")
        out.push(pcm)
        out.flush()
