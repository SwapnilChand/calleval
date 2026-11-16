"""Terminal output helpers: colour only on a real terminal (and never with NO_COLOR)."""
import os, sys

ON = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
CODES = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33", "cyan": "36"}
STATUS = {"PASS": ("✓", "green"), "FAIL": ("✗", "red"), "FLAKY": ("~", "yellow"), "INCONCLUSIVE": ("·", "dim"),
          "UNJUDGED": ("·", "dim"), "VOID": ("·", "dim"), "ERROR": ("!", "red")}


def c(text, *styles):
    return f"\033[{';'.join(CODES[s] for s in styles)}m{text}\033[0m" if ON and styles else str(text)


def status(st, width=0):
    sym, col = STATUS.get(st, ("?", "dim"))
    return c(f"{sym} {st}".ljust(width), col, "bold" if st in ("FAIL", "PASS") else "dim") if col != "dim" else c(f"{sym} {st}".ljust(width), "dim")


def header(title, *parts):
    print(c(f"\n {title}", "bold", "cyan") + ("  " + c("·", "dim") + "  " + f"  {c('·', 'dim')}  ".join(parts) if parts else ""))


def line(sym, color, text, extra=""):
    print(f" {c(sym, color)} {text}" + (f"  {c(extra, 'dim')}" if extra else ""))


def hint(text):
    print(c(f"\n next: {text}", "dim"))


def error(msg, fix=""):
    print(f"{c('error:', 'red', 'bold')} {msg}", file=sys.stderr)
    if fix:
        print(c(f"  → {fix}", "dim"), file=sys.stderr)


def step(msg):
    print(c(f"  … {msg}", "dim"), flush=True)


def ask(question, options=None, default=None):
    """Interactive question. options: list of (key, label). Non-interactive: returns default."""
    if not sys.stdin.isatty():
        return default
    print(c(f"\n {question}", "bold"))
    for i, (k, label) in enumerate(options or [], 1):
        print(f"  {c(str(i), 'cyan')}) {label}")
    while True:
        r = input(f" {'choose' if options else ''} [{default or ''}]: ".replace("  ", " ")).strip()
        if not r:
            return default
        if options and r.isdigit() and 1 <= int(r) <= len(options):
            return options[int(r) - 1][0]
        if options and r in [k for k, _ in options]:
            return r
        if not options:
            return r
        print(c("  not an option, try again", "yellow"))
