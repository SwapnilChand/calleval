#!/usr/bin/env bash
# usage: ./calleval.sh run --agent maya ...   (text runs need only python3; voice runs need .venv, see docs/LIVEKIT_PLAN.md)
cd "$(dirname "$(readlink -f "$0")")"
PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python
exec $PY -m calleval "$@"
