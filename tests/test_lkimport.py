"""No-key check: a LiveKit agent file is read (never run) into instructions, tools, roles, formats."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calleval.lkimport import extract, to_agent_json

f = extract((Path(__file__).resolve().parents[1] / "examples" / "livekit_agent.py").read_text())
assert f["instructions"].startswith("You are Sam"), f["instructions"]
names = [t["function"]["name"] for t in f["tools"]]
assert names == ["check_slots", "book_visit"], names
book = f["tools"][1]["function"]["parameters"]
assert book["required"] == ["patient_name", "date", "time"] and "phone" not in book["required"], book
assert f["tools"][0]["function"]["parameters"]["properties"]["treatment"]["enum"] == ["cleaning", "filling", "checkup"]
assert f["mock"]["book_visit"]["status"] == "booked"
d, roles = to_agent_json("x", f)
assert roles == {"lookup_tool": "check_slots", "book_tool": "book_visit"}, roles
assert d["mock"]["formats"]["book_visit"]["time"] == r"^\d{2}:\d{2}$"
print("OK")
