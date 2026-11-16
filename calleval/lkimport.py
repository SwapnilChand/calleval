"""Read a LiveKit agent file (Python, never executed) and extract what calleval needs: instructions, tools, greeting, speech stack."""
import ast

SIMPLE = {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}


def _schema(node):
    if node is None:
        return {"type": "string"}
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):             # X | None
        parts = [n for n in (node.left, node.right) if not (isinstance(n, ast.Constant) and n.value is None)]
        return _schema(parts[0]) if parts else {"type": "string"}
    if isinstance(node, ast.Subscript):
        base = ast.unparse(node.value).split(".")[-1]
        if base == "Literal":
            vals = [e.value for e in (node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]) if isinstance(e, ast.Constant)]
            return {"type": "string", "enum": vals}
        if base in ("list", "List"):
            return {"type": "array", "items": _schema(node.slice)}
        if base == "Optional":
            return _schema(node.slice)
    name = ast.unparse(node)
    return {"type": SIMPLE.get(name, "string")}


def _doc_args(doc):
    """Google-style 'Args:' section -> {param: description}."""
    out, on = {}, False
    for line in (doc or "").splitlines():
        t = line.strip()
        if t.lower() in ("args:", "arguments:", "parameters:"):
            on = True
        elif on and ":" in t and not t.endswith(":"):
            k, v = t.split(":", 1)
            out[k.strip().split(" ")[0]] = v.strip()
        elif on and not t:
            on = False
    return out


def _const_strings(tree):
    """Module-level NAME = "string" constants, so instructions=NAME resolves."""
    env = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            try:
                v = ast.literal_eval(n.value)
                if isinstance(v, str):
                    env[n.targets[0].id] = v
            except Exception:
                pass
    return env


def _text(node, env):
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.JoinedStr):                                            # f-string: keep the {placeholders}
        return ast.unparse(node)[2:-1]
    try:
        v = ast.literal_eval(node)
        return v if isinstance(v, str) else None
    except Exception:
        return None


def extract(source):
    tree = ast.parse(source)
    env = _const_strings(tree)
    found = {"instructions": None, "welcome": None, "tools": [], "mock": {}, "stack": {}, "notes": []}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            fn = ast.unparse(n.func)
            kw = {k.arg: k.value for k in n.keywords if k.arg}
            if fn.endswith("__init__") or fn.split(".")[-1] == "Agent":
                if "instructions" in kw and not found["instructions"]:
                    found["instructions"] = _text(kw["instructions"], env)
            if fn.split(".")[-1] == "AgentSession":
                for k in ("stt", "llm", "tts"):
                    if k in kw:
                        found["stack"][k] = ast.unparse(kw[k])
            if fn.endswith("generate_reply") and "instructions" in kw and not found["welcome"]:
                found["welcome"] = _text(kw["instructions"], env)
            if fn.endswith(".say") and n.args and not found["welcome"]:
                found["welcome"] = _text(n.args[0], env)
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)):
            decs = [ast.unparse(d.func if isinstance(d, ast.Call) else d).split(".")[-1] for d in n.decorator_list]
            if "function_tool" not in decs:
                continue
            doc = ast.get_docstring(n) or ""
            argdoc = _doc_args(doc)
            props, req = {}, []
            args = n.args.args
            defaults = [None] * (len(args) - len(n.args.defaults)) + list(n.args.defaults)
            for a, d in zip(args, defaults):
                if a.arg in ("self", "cls", "context", "ctx") or (a.annotation and "RunContext" in ast.unparse(a.annotation)):
                    continue
                props[a.arg] = {**_schema(a.annotation), **({"description": argdoc[a.arg]} if a.arg in argdoc else {})}
                if d is None:
                    req.append(a.arg)
            found["tools"].append({"type": "function", "function": {
                "name": n.name, "description": doc.split("\n\n")[0].replace("\n", " ").strip(),
                "parameters": {"type": "object", "properties": props, "required": req}}})
            for r in (x for x in ast.walk(n) if isinstance(x, ast.Return) and x.value is not None):
                try:
                    found["mock"].setdefault(n.name, ast.literal_eval(r.value))   # first literal return = the happy path as written
                except Exception:
                    pass
            if n.name not in found["mock"]:
                found["notes"].append(f"tool '{n.name}' returns a computed value: edit mock.tools['{n.name}'] in agent.json")
    if not found["instructions"]:
        found["notes"].append("could not read the instructions (built at runtime?): paste them into prompt.md")
    return found


ROLES = {"book_tool": ("book", "schedule", "reserve"), "lookup_tool": ("check", "slot", "avail", "lookup", "search", "find"),
         "change_tool": ("reschedule", "cancel", "change", "update", "modify"), "transfer_tool": ("transfer", "handoff", "escalate", "human"),
         "caller_tool": ("caller", "identify", "customer", "profile")}
FORMATS = (("YYYY-MM-DD HH:MM:SS", r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$"), ("YYYY-MM-DD", r"^\d{4}-\d{2}-\d{2}$"), ("HH:MM", r"^\d{2}:\d{2}$"))


def to_agent_json(name, f):
    """Build agent.json content from extract() output; returns (dict, notes)."""
    formats, roles = {}, {}
    for t in f["tools"]:
        fn = t["function"]
        for pn, p in fn["parameters"]["properties"].items():
            for marker, rx in FORMATS:
                if marker in p.get("description", ""):
                    formats.setdefault(fn["name"], {})[pn] = rx
                    break
        for role, words in ROLES.items():
            if role not in roles and any(w in fn["name"].lower() for w in words):
                roles[role] = fn["name"]
    first = (f["instructions"] or "").split(".")[0].strip()
    d = {"name": name, "welcome": "TODO: the first line the agent says", "welcome_instruction": f["welcome"], "tools": f["tools"],
         "mock": {"tools": f["mock"], "formats": formats}, "source_stack": f["stack"],
         "case_vars": {"task": first[:160] or "TODO: what a customer calls this agent for", **roles}}
    return d, roles
