"""`calleval doctor` (what works / what is missing) and `calleval setup` (choose a stack, install missing local pieces, write calleval.json)."""
import json, os, shutil, subprocess, sys, tarfile, tempfile, urllib.request
from pathlib import Path
from .core import ROOT, load_env

TOOLS, VOICES = ROOT / ".tools", ROOT / ".tools" / "voices"
HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/{n}/medium/en_US-{n}-medium.onnx"
GROQ = {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY"}
GEM = {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "key_env": "GEMINI_API_KEY"}


def llm(base, model, mt, temp, extra=None):
    return {**base, "model": model, "max_tokens": mt, "temperature": temp, "extra": extra or {}}


PRESETS = {
    "local": ("Everything on this machine, no keys: Ollama LLM, faster-whisper STT, Piper TTS. Slowest and weakest models.", lambda m: {
        "agent_llm": llm({"base_url": "http://127.0.0.1:11434/v1", "key_env": ""}, m, 700, 0.2),
        "persona_llm": llm({"base_url": "http://127.0.0.1:11434/v1", "key_env": ""}, m, 400, 0.8),
        "voice": {"stt": "local", "stt_model": "base.en", "persona_llm": llm({"base_url": "http://127.0.0.1:11434/v1", "key_env": ""}, m, 80, 0.7)}}),
    "free-keys": ("Hosted free tiers: Gemini (LLMs) + Groq (speech-to-text). Needs GEMINI_API_KEY and GROQ_API_KEY in .env; TTS stays local.", lambda m: {
        "agent_llm": llm(GEM, "gemini-3.5-flash-lite", 700, 0.2),
        "persona_llm": llm(GEM, "gemini-3.5-flash-lite", 400, 0.8),
        "judge_llm": llm(GROQ, "openai/gpt-oss-120b", 1500, 0, {"reasoning_effort": "medium"}),
        "voice": {"stt": "groq", "stt_model": "whisper-large-v3-turbo", "persona_llm": llm(GEM, "gemini-3.5-flash-lite", 80, 0.7)}}),
}


def rel(p):
    return str(Path(p).relative_to(ROOT)) if str(p).startswith(str(ROOT)) else str(p)


def venv_python():
    p = ROOT / ".venv" / "bin" / "python"
    return p if p.exists() else None


def has_py(mod):
    py = venv_python()
    return bool(py) and subprocess.run([str(py), "-c", f"import {mod}"], capture_output=True).returncode == 0


def http_ok(url):
    try:
        urllib.request.urlopen(url, timeout=2)
        return True
    except Exception:
        return False


def checks(cfg):
    """[(id, ok, detail, how_to_fix)] for the stack in `cfg` (merged config)."""
    v, ev = cfg["voice"], os.environ
    rows = [("python", sys.version_info >= (3, 11), f"Python {sys.version.split()[0]} (3.11+ needed)", "install Python 3.11+")]
    for name in ("agent_llm", "persona_llm"):
        c = cfg[name]
        local = any(h in c["base_url"] for h in ("127.0.0.1", "localhost"))
        if local:
            up = http_ok(c["base_url"].rsplit("/v1", 1)[0] + "/api/tags")
            rows.append((f"server:{c['base_url']}", up, f"local model server running at {c['base_url'].rsplit('/v1', 1)[0]}", "install Ollama and run `ollama serve`"))
            if up:
                tags = json.load(urllib.request.urlopen(c["base_url"].rsplit("/v1", 1)[0] + "/api/tags"))["models"]
                have = any(t["name"].startswith(c["model"]) for t in tags)
                rows.append((f"model:{c['model']}", have, f"local model {c['model']} is pulled", f"ollama pull {c['model']}"))
        else:
            rows.append((f"{c['key_env']}:key", bool(ev.get(c["key_env"])), f"{c['key_env']} is set (hosted model {c['model']})", f"add {c['key_env']}=... to .env"))
    voice = [("voice:ffmpeg", bool(shutil.which("ffmpeg")), "ffmpeg installed (turns recordings into audio.mp3)", "install ffmpeg with your package manager"),
             ("voice:venv", bool(venv_python()), "voice packages environment (.venv)", "run `calleval setup --install voice`"),
             ("voice:livekit", has_py("livekit.agents"), "call framework installed (livekit-agents)", "run `calleval setup --install voice`"),
             ("voice:server", (TOOLS / "livekit-server").exists() or bool(shutil.which("livekit-server")), "local call server (livekit-server)", "run `calleval setup --install voice`"),
             ("voice:piper", has_py("piper") and (VOICES / f"{v['twin_voice']}.onnx").exists() and (VOICES / f"{v['persona_voice']}.onnx").exists(), "local voices downloaded (Piper, one per speaker)", "run `calleval setup --install voice`")]
    if v["stt"] == "local":
        voice.append(("voice:stt", has_py("faster_whisper"), "local speech-to-text installed (faster-whisper)", "run `calleval setup --install voice`"))
    elif v["stt"] == "groq":
        voice.append(("voice:stt-key", bool(ev.get(v.get("stt_key_env", "GROQ_API_KEY"))), "GROQ_API_KEY is set (hosted speech-to-text)", "add GROQ_API_KEY=... to .env"))
    seen, uniq = set(), []
    for r in rows:
        if r[0] not in seen:
            seen.add(r[0]); uniq.append(r)
    return uniq, voice


def doctor(a):
    from .core import load_config
    load_env()
    cfg = load_config()
    text, voice = checks(cfg)
    from . import ui

    def section(title, rows):
        print(ui.c(f"\n {title}", "bold", "cyan"))
        for i, ok, d, fix in rows:
            print(f"  {ui.c('✓', 'green') if ok else ui.c('✗', 'red')} {d}" + ("" if ok else ui.c(f"   → {fix}", "dim")))
    section("Text runs (Python only)", text)
    section("Voice runs (real audio, optional extra)", voice)
    g = bool(os.environ.get("GEMINI_API_KEY"))
    print(ui.c("\n Optional", "bold", "cyan"))
    print(f"  {ui.c('✓', 'green') if g else ui.c('-', 'dim')} spoken-form hints: a listening model transcribes the agent's audio word for word"
          + ("" if g else ui.c("   → set GEMINI_API_KEY in .env to enable", "dim")))
    good = all(ok for _, ok, *_ in text)
    print("\n " + (ui.c("Text runs are ready.", "green", "bold") if good else ui.c("Fix the ✗ items above to run tests.", "yellow", "bold"))
          + ("" if all(ok for _, ok, *_ in voice) else ui.c(" Voice runs need the extra pieces: calleval setup --install voice", "dim")))
    if a.json:
        print(json.dumps([{"id": i, "ok": ok} for i, ok, *_ in text + voice]))
    return all(ok for _, ok, *_ in text)


def download(url, dest, min_bytes=0):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    have = dest.stat().st_size if dest.exists() else 0
    req = urllib.request.Request(url, headers={"User-Agent": "calleval", **({"Range": f"bytes={have}-"} if have else {})})
    try:
        with urllib.request.urlopen(req, timeout=120) as r, open(dest, "ab" if have and r.status == 206 else "wb") as f:
            shutil.copyfileobj(r, f)
    except urllib.error.HTTPError as e:
        if e.code != 416:                                  # 416 = already complete
            raise
    return dest


def step(msg):
    from . import ui
    print(ui.c(f"  … {msg}", "dim"), flush=True)


def install_voice(cfg):
    from . import ui
    uv = shutil.which("uv")
    pkgs = ["livekit-agents", "livekit-plugins-openai", "livekit-plugins-silero", "piper-tts"]
    if cfg["voice"]["stt"] == "local":
        pkgs.append("faster-whisper")
    if cfg["voice"]["stt"] == "groq":
        pkgs.append("livekit-plugins-groq")
    step("Python packages (call framework, local voices, speech-to-text): a few minutes the first time")
    if not venv_python():
        subprocess.run([uv, "venv", "-q", "--python", "3.14", str(ROOT / ".venv")] if uv else [sys.executable, "-m", "venv", str(ROOT / ".venv")], check=True)
    py = str(venv_python())
    subprocess.run([uv, "pip", "install", "-q", "--python", py, *pkgs] if uv else [py, "-m", "pip", "install", "-q", *pkgs], check=True)
    if not (TOOLS / "livekit-server").exists() and not shutil.which("livekit-server"):
        step("local call server (about 20 MB)")
        rel_ = json.load(urllib.request.urlopen("https://api.github.com/repos/livekit/livekit/releases/latest"))
        asset = next(x for x in rel_["assets"] if x["name"].endswith("linux_amd64.tar.gz"))
        with tempfile.TemporaryDirectory() as t:
            tgz = download(asset["browser_download_url"], Path(t) / "s.tgz")
            tarfile.open(tgz).extract("livekit-server", t)
            TOOLS.mkdir(exist_ok=True)
            shutil.move(str(Path(t) / "livekit-server"), TOOLS / "livekit-server")
            (TOOLS / "livekit-server").chmod(0o755)
    step("two local voices (about 60 MB each)")
    for n in ("lessac", "ryan"):
        url = HF.format(n=n)
        for suffix in ("", ".json"):
            download(url + suffix, VOICES / f"en_US-{n}-medium.onnx{suffix}")


def ask(q, default="y", yes=False):
    if yes or not sys.stdin.isatty():
        return yes
    r = input(f"{q} [{'Y/n' if default == 'y' else 'y/N'}] ").strip().lower() or default
    return r.startswith("y")


def setup(a):
    from .core import load_config
    load_env()
    cfgp = ROOT / "calleval.json"
    preset = a.preset
    if not preset and sys.stdin.isatty():
        from . import ui
        print(ui.c("\n Choose a stack", "bold", "cyan"))
        for k, (d, _) in PRESETS.items():
            print(f"  {ui.c(k.ljust(10), 'bold')} {d}")
        preset = input("preset [local]: ").strip() or "local"
    preset = preset or "local"
    new = PRESETS[preset][1](a.llm_model)
    cur = json.loads(cfgp.read_text()) if cfgp.exists() else {}
    cur.update({k: v for k, v in new.items() if k != "voice"})
    cur["voice"] = {**cur.get("voice", {}), **new["voice"]}
    cfgp.write_text(json.dumps(cur, indent=2) + "\n")
    from . import ui
    ui.header("calleval setup", f"preset: {preset}")
    ui.line("✓", "green", f"wrote {rel(cfgp)}", "your personal stack choice; gitignored")
    cfg = load_config()
    if (a.install == "voice") or (not a.install and ask("Install the voice-run pieces (about 600 MB: Python packages, livekit-server, 2 Piper voices)?", yes=a.yes)):
        install_voice(cfg)
        from . import ui
        ui.line("✓", "green", "voice pieces installed")
    doctor(type("A", (), {"json": False})())
    if preset == "local":
        from . import ui
        print(ui.c(f"\n Local models: install Ollama, run `ollama serve`, then `ollama pull {a.llm_model}` (about 2 GB). "
                   "Small local models follow long prompts and tools poorly; `calleval setup --preset free-keys` gives better results.", "dim"))
