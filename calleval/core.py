"""Paths, config, env loading, agent/case loading. Zero third-party deps."""
import datetime as dt, json, os, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LOCAL_LLM = {"base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5:3b", "key_env": "", "max_tokens": 700, "temperature": 0.2, "extra": {}}

DEFAULTS = {
    # Zero-key default: everything runs on this machine (Ollama for LLMs, faster-whisper for STT, Piper for TTS).
    # `calleval setup` can switch any part to a hosted model by key (see calleval/setup.py PRESETS).
    "agent_llm":   dict(LOCAL_LLM),
    "persona_llm": {**LOCAL_LLM, "max_tokens": 400, "temperature": 0.8},
    "judge_llm":   {**LOCAL_LLM, "max_tokens": 1500, "temperature": 0},     # only used with `judge --llm`; Claude Code judges by default
    "voice": {"stt": "local", "stt_model": "base.en", "tts": "piper",
              "twin_voice": "en_US-lessac-medium", "persona_voice": "en_US-ryan-medium", "max_seconds": 150,
              "persona_llm": {**LOCAL_LLM, "max_tokens": 80, "temperature": 0.7},
              "gemini": {"twin_model": "gemini-3.8-flash-lite-tts", "persona_model": "gemini-3.8-flash-tts",
                         "twin_voice": "Kore", "persona_voice": "Puck"},
              "livekit_url": "ws://127.0.0.1:7880", "api_key": "devkey", "api_secret": "secretsecretsecretsecretsecret00"},
    "now": "2026-11-17 10:30",   # pinned so "tomorrow"/"Thursday" mean the same on every run
    "from_number": "9876543210",
    "turns": 8,                  # max customer turns per conversation
    "runs": 3,
}


def load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def config_path():
    return Path(os.environ["CALLEVAL_CONFIG"]) if os.environ.get("CALLEVAL_CONFIG") else ROOT / "calleval.json"   # override: try a stack without touching your own


def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))
    p = config_path()
    if p.exists():
        for k, v in json.loads(p.read_text()).items():
            cfg[k] = {**cfg[k], **v} if isinstance(v, dict) and isinstance(cfg.get(k), dict) else v
    return cfg


def date_vars(now_str):
    now = dt.datetime.strptime(now_str, "%Y-%m-%d %H:%M")
    d = lambda n: (now + dt.timedelta(days=n)).strftime("%Y-%m-%d")
    thu = d((3 - now.weekday()) % 7 or 7)            # next Thursday strictly after today
    return {"thursday": thu, "now": now_str, "today": d(0), "tomorrow": d(1), "day_after": d(2),
            "weekday": now.strftime("%A"), "time": now.strftime("%H:%M")}


def versions(agent):
    base = ROOT / "agents" / agent
    return sorted((int(p.name[1:]) for p in base.glob("v*") if p.name[1:].isdigit()))


def load_agent(name, version=None):
    v = version or f"v{versions(name)[-1]}"
    d = ROOT / "agents" / name / v
    a = json.loads((d / "agent.json").read_text())
    a["prompt"] = (d / "prompt.md").read_text()
    a["name"], a["version"] = name, v
    return a


class Skip(Exception):
    """Case references a variable this agent does not define (e.g. no transfer tool)."""


def fill(obj, vars_):
    """Replace {name} placeholders recursively. Regex quantifiers like {4} never match [a-z_]+."""
    if isinstance(obj, str):
        def sub(m):
            if m.group(1) not in vars_:
                raise Skip(m.group(1))
            return str(vars_[m.group(1)])
        return re.sub(r"\{([a-z_]+)\}", sub, obj)
    if isinstance(obj, list):
        return [fill(x, vars_) for x in obj]
    if isinstance(obj, dict):
        return {fill(k, vars_): fill(v, vars_) for k, v in obj.items()}
    return obj


def load_cases(selector="all", split="all", agent=None):
    """selector: all | universal | generated | comma-separated case ids."""
    out = []
    for p in sorted((ROOT / "cases").rglob("*.json")):
        parts = p.relative_to(ROOT / "cases").parts
        if agent and len(parts) > 2 and parts[0] == "generated" and parts[1] != agent:
            continue                                   # generated cases belong to the agent they were written for
        data = json.loads(p.read_text())
        for c in (data if isinstance(data, list) else [data]):
            c["_file"] = str(p.relative_to(ROOT))
            out.append(c)
    if selector in ("universal", "generated"):
        out = [c for c in out if f"/{selector}/" in "/" + c["_file"]]
    elif selector != "all":
        ids = selector.split(",")
        out = [c for c in out if c["id"] in ids]
    if split != "all":
        out = [c for c in out if c.get("split", "train") == split]
    return out
