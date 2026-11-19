"""Labelled requests for measuring tool selection.

Each case: (what the user says, expected tool or None, text that must appear in the arguments or None).
None as the tool means the right behaviour is to answer in words, with no tool call.
Requests the instant-command router already handles are left out, because the router answers those without the model.
"""

CASES = [
    # apps and Mac
    ("open Spotify", "open_app", "spotify"),
    ("launch Safari for me", "open_app", "safari"),
    ("close Notes", "quit_app", "notes"),
    ("quit Slack", "quit_app", "slack"),
    ("run my morning shortcut", "run_shortcut", "morning"),
    ("make a note that the boiler needs servicing", "make_note", "boiler"),
    ("what's on my screen", "look_at_screen", None),
    # calendar, time, tasks
    ("what's on my calendar today", "calendar", None),
    ("do I have anything on tomorrow", "calendar", "tomorrow"),
    ("what's on my to do list", "todays_tasks", None),
    ("add buy milk to my list", "add_task", "milk"),
    ("I finished the laundry", "complete_task", "laundry"),
    ("take the dentist off my list", "remove_task", "dentist"),
    ("I walked 8000 steps today", "log_steps", "8000"),
    ("how have my habits been over the last week", "habit_report", None),
    ("give me my morning briefing", "morning_briefing", None),
    # reminders
    ("remind me to call mum in 20 minutes", "set_reminder", "mum"),
    ("remind me to take the bins out at 7pm", "set_reminder", "bins"),
    ("what reminders do I have", "list_reminders", None),
    # information
    ("what's the weather in Paris", "weather", "paris"),
    ("will it rain today", "rain_today", None),
    ("how long to get to Heathrow", "travel_time", "heathrow"),
    ("find a good curry house nearby", "find_nearby", None),
    ("search the web for the latest Ollama release", "web_search", "ollama"),
    ("who won the Premier League last season", "web_search", None),
    # memory
    ("remember that my passport expires in March", "remember", "passport"),
    ("forget that I like jazz", "forget", "jazz"),
    ("I'm allergic to peanuts, please remember that", "remember", "peanut"),
    # household log
    ("log that I finished my dissertation draft", "log_note", "dissertation"),
    ("what did I do over the last three days", "read_log", None),
    # smart home beyond the fast lane
    ("turn the bedroom lamp to 20 percent", "control_device", "bedroom"),
    ("switch off the desk lamp", "control_device", "desk"),
    # hard questions go to Claude
    ("write me a short cover letter for a lab technician role", "ask_claude", None),
    ("explain how a transformer neural network works in detail", "ask_claude", None),
    ("plan a three day trip to Edinburgh on a budget", "ask_claude", None),
    # should answer without a tool
    ("thanks, that's all", None, None),
    ("how are you today", None, None),
    ("tell me a joke", None, None),
    ("what is two plus two", None, None),
    ("good morning", None, None),
    # tricky: remarks that sound like commands but are not
    ("I left the light on at work", None, None),
    ("the music was too loud at the pub last night", None, None),
    ("my friend's name is Alex and he lives in Leeds", None, None),
]
