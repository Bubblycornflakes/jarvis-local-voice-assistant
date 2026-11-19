"""JARVIS's skills as an MCP server, so the VoiceChat voice model can use them.
VoiceChat allows at most five tools, so these are the five that matter most.
Run by VoiceChat itself (see voicechat/mcp.json); nothing may print to stdout."""
import datetime as dt
import subprocess

from mcp.server.mcpserver import MCPServer

from jarvis import household, tools

server = MCPServer("jarvis", instructions="JARVIS household skills: lights, weather, journeys, reminders, daily list.")


@server.tool(description="Switch the lights on or off, or set brightness from 1 to 100.")
def lights(action: str, brightness: int = 0) -> str:
    """action: 'on' or 'off'. brightness: 1-100, or 0 to leave it unchanged."""
    return tools.control_device("all", "off" if action.lower() == "off" else "on", brightness)


@server.tool(description="Current weather. Leave city empty for home (London).")
def weather(city: str = "") -> str:
    return tools.weather(city)


@server.tool(description="Journey time from home to a place, by car and by public transport.")
def travel_time(destination: str) -> str:
    return tools.travel_time(destination)


@server.tool(description="Set a reminder. when: e.g. 'in 20 minutes', '6pm', 'tomorrow 9am'.")
def reminder(text: str, when: str) -> str:
    t = tools._parse_when(when)
    if not t:
        return f"I couldn't work out when '{when}' is."
    # Apple Reminders alerts on the Mac (and iPhone) even when this voice chat is closed
    safe = text.replace('"', "'")
    script = f'''
    set d to current date
    set year of d to {t.year}
    set month of d to {t.month}
    set day of d to {t.day}
    set time of d to {t.hour * 3600 + t.minute * 60}
    tell application "Reminders" to make new reminder with properties {{name:"{safe}", remind me date:d}}'''
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        return "I couldn't add it to Reminders; it may need permission in System Settings, Privacy, Reminders."
    when_said = t.strftime("%-I %p" if t.minute == 0 else "%-I:%M %p").replace("AM", "a.m.").replace("PM", "p.m.")
    return f"Reminder set for {when_said}{'' if t.date() == dt.date.today() else ' tomorrow'}: {text}."


@server.tool(description="Today's to-do list and daily habits. action: 'show', 'done' (tick off item), or 'add' (add item).")
def daily_list(action: str = "show", item: str = "") -> str:
    action = action.lower()
    if action == "done" and item:
        return tools.complete_task(item)
    if action == "add" and item:
        return tools.add_task(item)
    return tools.todays_tasks()


if __name__ == "__main__":
    server.run("stdio")
