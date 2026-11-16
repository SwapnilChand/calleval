"""Raw-schema function tools for the twin, backed by the mock clinic backend (shared by the room worker and the debugger entrypoint)."""
import json
from livekit.agents import RunContext, function_tool
from ..mocks import call_tool

END_TOOLS = ("end_call", "transfer_call")


def build_tools(spec, log=None, on_end=None):
    def tool(t):
        f = t["function"]

        async def handler(raw_arguments: dict[str, object], context: RunContext):
            res = call_tool({"tools": spec["twin"]["tools"], "mock": spec["twin"]["mock"]}, spec["case"], f["name"], raw_arguments)
            if log:
                log("tool", name=f["name"], args=raw_arguments, result=res)
            if on_end and f["name"].startswith(END_TOOLS):
                on_end()
            return json.dumps(res)
        return function_tool(handler, raw_schema={"name": f["name"], "description": f.get("description", ""),
                                                  "parameters": f.get("parameters", {"type": "object", "properties": {}})})
    return [tool(t) for t in spec["twin"]["tools"]]
