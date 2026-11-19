#!/bin/zsh
cd "$(dirname "$0")"
pgrep -x ollama >/dev/null || (open -a Ollama 2>/dev/null || ollama serve >/dev/null 2>&1 &)
.venv/bin/python main.py
