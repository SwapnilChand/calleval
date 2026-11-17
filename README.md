# calleval

**Test a voice agent before your customers do.** A simulated customer talks to your agent, an LLM judges each call against test cases, and you get a report that shows what passed, what failed, and why, with quoted evidence. Run it as text (fast, cheap) or as a **real audio call** (finds what text can't: misheard names, awkward number reading, slow replies). It runs on your machine; API keys are optional.

[![calleval demo: a real call where the agent mishears a name and the report catches it](docs/demo.gif)](docs/demo.mp4)

*Preview. [Full demo with sound](docs/demo.mp4): the agent mishears "Neha Kapoor" as "Ne Kippur", books under it, and the report catches it.*

## Install
```bash
git clone https://github.com/SwapnilChand/calleval && cd calleval && ./install.sh
```
Then run one command, or ask Claude Code:
```bash
calleval start                 # guided: setup, run, judge, results, report in your browser
```
or, in Claude Code: *"test my voice agent with calleval"*.

**Step-by-step guide, every output explained, keys and costs, troubleshooting: [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md)** · [How it works](docs/HOW_IT_WORKS.md)

MIT licensed.
