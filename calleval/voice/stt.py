"""Local speech-to-text (faster-whisper, CPU, no key). Non-streaming: the session wraps it with VAD."""
import asyncio
import numpy as np
from livekit import rtc
from livekit.agents import stt


class LocalWhisperSTT(stt.STT):
    def __init__(self, model="base.en", language="en"):
        super().__init__(capabilities=stt.STTCapabilities(streaming=False, interim_results=False))
        from faster_whisper import WhisperModel          # downloads the model on first use (base.en ~145 MB)
        self._m, self._lang = WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=4), language

    async def _recognize_impl(self, buffer, *, language, conn_options):
        frame = rtc.combine_audio_frames(buffer)
        audio = np.frombuffer(frame.data, dtype=np.int16).astype(np.float32) / 32768.0
        if frame.num_channels > 1:
            audio = audio.reshape(-1, frame.num_channels).mean(axis=1)
        if frame.sample_rate != 16000:                    # linear resample is enough for speech recognition
            n = int(len(audio) * 16000 / frame.sample_rate)
            audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)

        def run():
            segs, _ = self._m.transcribe(audio, language=self._lang, beam_size=1, vad_filter=False)
            return " ".join(s.text.strip() for s in segs).strip()
        text = await asyncio.to_thread(run)
        return stt.SpeechEvent(type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                               alternatives=[stt.SpeechData(language=self._lang, text=text)])
