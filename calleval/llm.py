"""One function: OpenAI-compatible chat completions over urllib. Works for Groq, Gemini (OpenAI endpoint),
OpenRouter, Cerebras, OpenAI, local Ollama. `fake:<name>` base_url routes to FAKES for tests."""
import json, os, time, urllib.error, urllib.request

USAGE = {"calls": 0, "prompt": 0, "cached": 0, "completion": 0}   # running totals; sim reports deltas
FAKES = {}   # name -> fn(messages, tools) -> message dict


def chat(cfg, messages, tools=None):
    if cfg["base_url"].startswith("fake:"):
        return FAKES[cfg["base_url"][5:]](messages, tools), {}
    key = os.environ.get(cfg.get("key_env", ""), "")
    if not key and not any(h in cfg["base_url"] for h in ("localhost", "127.0.0.1")):
        raise RuntimeError(f"missing env var {cfg.get('key_env')} (put it in .env, or switch stack with `calleval setup`)")
    body = {"model": cfg["model"], "messages": messages, "max_tokens": cfg.get("max_tokens", 400),
            "temperature": cfg.get("temperature", 0.3), **cfg.get("extra", {})}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(
        cfg["base_url"].rstrip("/") + "/chat/completions", json.dumps(body).encode(),
        {"Authorization": "Bearer " + (key or "none"), "Content-Type": "application/json", "User-Agent": "calleval/0.1"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.load(r)
            u = d.get("usage", {})
            USAGE["calls"] += 1; USAGE["prompt"] += u.get("prompt_tokens", 0); USAGE["completion"] += u.get("completion_tokens", 0)
            USAGE["cached"] += (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
            return d["choices"][0]["message"], u
        except urllib.error.HTTPError as e:
            detail = e.read()[:400].decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503) and attempt < 5:   # rate limit / transient: wait and retry
                time.sleep(min(float(e.headers.get("retry-after") or 5 * 2 ** attempt), 90))
                continue
            raise RuntimeError(f"LLM HTTP {e.code} from {cfg['base_url']}: {detail}")
