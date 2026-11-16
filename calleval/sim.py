"""One simulated phone call in text: agent-under-test <-> persona (customer). Writes transcript.json."""
import json, re
from .core import fill
from .llm import USAGE, chat
from .mocks import call_tool

PERSONA = """You are role-playing a CUSTOMER on a phone call with a business's voice assistant. You are NOT an assistant.
Who you are: {persona}
Your goal on this call: {goal}
Quirks to act out (do them naturally at the right moment, never announce them): {quirks}
Rules: speak like on a phone, 1-2 short sentences, no lists, no stage directions, no quotation marks. Write ONLY your own next line, never what the assistant says or does. Never say you are an AI
or a simulation. Answer only what is asked unless your goal needs more. Your phone number is {phone}.
When your goal is finished, or the assistant ended or transferred the call, say a brief goodbye and end that message with [END]. Never use [END] in your first three replies: the call has barely started and the assistant still has to act on your request."""


def run_conversation(agent, case, cfg, pvars):
    a_msgs = [{"role": "system", "content": fill_prompt(agent["prompt"], pvars)},   # static prefix first: cache-friendly
              {"role": "assistant", "content": agent["welcome"]}]
    tr = [{"i": 0, "role": "agent", "text": agent["welcome"]}]
    tools_log, err = [], None
    persona = PERSONA.format(persona=case["persona"], goal=case["goal"], phone=pvars["from_number"],
                             quirks="; ".join(case.get("quirks", [])) or "none")
    ended = "max_turns"
    u0 = dict(USAGE)
    try:
        for t in range(cfg["turns"]):
            p_msgs = [{"role": "system", "content": persona}] + [
                {"role": "user" if x["role"] == "agent" else "assistant", "content": x["text"]} for x in tr]
            if t == 0 and case.get("opening"):
                text = case["opening"]
            else:
                msg, _ = chat(cfg["persona_llm"], p_msgs)
                text = (msg.get("content") or "").strip()
            end = "[END]" in text and t >= 2        # ignore premature [END] (persona models emit it too early)
            text = text.replace("[END]", "").strip() or "Okay, bye."
            text = " ".join(re.split(r"(?<=[.!?])\s*(?=[A-Z])", text)[:2])   # persona sometimes writes several future turns at once
            tr.append({"i": len(tr), "role": "customer", "text": text})
            a_msgs.append({"role": "user", "content": text})
            names = []
            for _ in range(5):                                   # tool loop, max 5 rounds per turn
                msg, bad = agent_chat(cfg, a_msgs, agent)
                if bad:                                           # model called a tool that does not exist
                    tools_log.append({"turn": len(tr), "name": bad, "args": {}, "result": {"error": "unknown tool (invalid call)"}})
                    names.append(bad)
                    if bad.startswith("end_call"):
                        ended = "agent_end"
                    clean = {"content": f"(invalid tool call: {bad})"}
                    break
                clean = {"role": "assistant", "content": msg.get("content") or ""}
                if msg.get("tool_calls"):
                    clean["tool_calls"] = msg["tool_calls"]
                a_msgs.append(clean)
                if not msg.get("tool_calls"):
                    break
                for tc in msg["tool_calls"]:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"].get("arguments") or "{}")
                        res = call_tool(agent, case, name, args)
                    except json.JSONDecodeError:
                        args, res = {"_raw": tc["function"].get("arguments")}, {"error": "arguments were not valid JSON"}
                    names.append(name)
                    tools_log.append({"turn": len(tr), "name": name, "args": args, "result": res})
                    a_msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(res)})
            tr.append({"i": len(tr), "role": "agent", "text": clean["content"] or "(no spoken reply)", "tools": names})
            if ended == "agent_end":
                break
            if end:
                ended = "customer_end"
                break
    except Exception as e:                                       # keep partial transcript; mark run as errored
        err, ended = str(e), "error"
    return {"turns": tr, "tool_calls": tools_log, "ended": ended, "error": err,
            "usage": {k: USAGE[k] - u0[k] for k in USAGE}}


def fill_prompt(prompt, pvars):
    for k in ("current_date", "current_time", "from_number"):
        prompt = prompt.replace("{" + k + "}", str(pvars[k]))
    return prompt


def agent_chat(cfg, a_msgs, agent):
    """Returns (message, None) or (None, bad_tool_name) when the provider rejects an unknown tool after 3 tries."""
    for _ in range(3):
        try:
            return chat(cfg["agent_llm"], a_msgs, tools=agent["tools"] or None)[0], None
        except RuntimeError as e:
            m = re.search(r"tool_use_failed.*?name\\?\": ?\\?\"([A-Za-z0-9_]+)", str(e))
            if not m:
                raise
            bad = m.group(1)
    return None, bad
