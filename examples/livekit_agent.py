"""A typical LiveKit agent file (the shape a customer would share)."""
from typing import Literal
from livekit.agents import Agent, AgentSession, JobContext, RunContext, function_tool, cli, AgentServer
from livekit.plugins import deepgram, elevenlabs, openai, silero

SYSTEM = (
    "You are Sam, the phone assistant for Green Leaf Dental. "
    "Be brief and warm. Never give medical advice. Confirm the date and time before booking."
)


class Dental(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=SYSTEM)

    @function_tool
    async def check_slots(self, context: RunContext, date: str, treatment: Literal["cleaning", "filling", "checkup"] = "checkup"):
        """Look up free appointment slots.

        Args:
            date: the day to check, as YYYY-MM-DD
            treatment: the kind of visit
        """
        return {"date": date, "slots": ["09:00", "11:30", "15:00"]}

    @function_tool()
    async def book_visit(self, context: RunContext, patient_name: str, date: str, time: str, phone: str | None = None):
        """Book a visit.

        Args:
            patient_name: the patient's full name
            date: YYYY-MM-DD
            time: HH:MM, 24 hour
            phone: contact number if the caller gives one
        """
        if not patient_name:
            return {"error": "name required"}
        return {"status": "booked", "confirmation": "GL-1042"}


server = AgentServer()


@server.rtc_session()
async def entry(ctx: JobContext):
    session = AgentSession(stt=deepgram.STT(model="nova-3"), llm=openai.LLM(model="gpt-4.1-mini"),
                           tts=elevenlabs.TTS(voice_id="abc"), vad=silero.VAD.load())
    await session.start(agent=Dental(), room=ctx.room)
    await session.generate_reply(instructions="Greet the caller as Sam from Green Leaf Dental and ask how you can help.")


if __name__ == "__main__":
    cli.run_app(server)
