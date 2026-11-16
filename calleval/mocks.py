"""Mock tool backend. Validates args against the tool's JSON schema (+ optional regex formats from
agent.json mock.formats) so a malformed call becomes an {"error": ...} the agent must handle."""
import re


def validate(schema, args, formats, skip=()):
    errs = []
    props = schema.get("properties", {})
    for r in schema.get("required", []):
        if r in skip:
            continue
        if r not in args or args[r] in (None, ""):
            errs.append(f"missing required param '{r}'")
    for k, v in args.items():
        p = props.get(k)
        if p is None:
            continue
        if "enum" in p and v not in p["enum"]:
            errs.append(f"'{k}' must be one of {p['enum']}, got {v!r}")
        if v is not None and k in formats and not re.search(formats[k], str(v)):
            errs.append(f"'{k}' has wrong format (expected /{formats[k]}/), got {v!r}")
    return errs


def call_tool(agent, case, name, args):
    spec = next((t for t in agent["tools"] if t["function"]["name"] == name), None)
    if spec is None:
        return {"error": f"unknown tool '{name}'"}
    mock = agent.get("mock", {})
    errs = validate(spec["function"].get("parameters", {}), args, mock.get("formats", {}).get(name, {}), mock.get("skip_required", {}).get(name, ()))
    if errs:
        return {"error": "; ".join(errs)}
    if name in case.get("mock_overrides", {}):        # case-specific world (e.g. force a timeout)
        return case["mock_overrides"][name]
    return mock.get("tools", {}).get(name, {"ok": True})
