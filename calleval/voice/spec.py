"""One voice call = one spec.json that both LiveKit workers read (twin = agent under test, persona = caller)."""
import json
from ..sim import PERSONA, fill_prompt

PERSONA_VOICE = PERSONA.split("When your goal is finished")[0] + (
    "When your goal is finished, or the assistant ended or transferred the call, say a brief goodbye and then call the end_call tool. "
    "Never call end_call in your first three replies. You are on a live phone call: the assistant speaks first. "
    "When you say a phone number or any digits, say them one digit at a time as words (nine eight seven six...). "
    "Each time you speak, say ONE short line (one or two sentences) and then stop and wait for the assistant to answer; never write several turns at once.")


def build_spec(agent, case, cfg, pvars, run_dir):
    persona = PERSONA_VOICE.format(persona=case["persona"], goal=case["goal"], phone=pvars["from_number"],
                                   quirks="; ".join(case.get("quirks", [])) or "none")
    spec = {"run_dir": str(run_dir), "case": case, "max_seconds": cfg.get("voice", {}).get("max_seconds", 150),
            "twin": {"prompt": fill_prompt(agent["prompt"], pvars), "welcome": agent["welcome"],
                     "tools": agent["tools"], "mock": agent.get("mock", {}), "llm": cfg["agent_llm"]},
            "persona": {"prompt": persona, "opening": case.get("opening"), "llm": cfg["voice"].get("persona_llm", cfg["persona_llm"])},
            "voice": cfg["voice"]}
    (run_dir).mkdir(parents=True, exist_ok=True)
    p = run_dir / "spec.json"
    p.write_text(json.dumps(spec, indent=1, ensure_ascii=False))
    return p
