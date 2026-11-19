#!/bin/zsh
# JARVIS Live: the full-duplex VoiceChat voice, with JARVIS's skills plugged in.
# Closes the main JARVIS app first, since both together don't fit in memory.
pkill -f "Python main.py" 2>/dev/null
ollama stop gpt-oss:20b >/dev/null 2>&1
clear
echo "JARVIS Live - just talk. Ctrl+C to stop."
exec /opt/homebrew/bin/speech voice-chat --greet \
  --mcp-config "$HOME/Jarvis/voicechat/mcp.json" --mcp-server jarvis \
  --system-prompt "$(cat "$HOME/Jarvis/voicechat/persona.txt")"
