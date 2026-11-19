"""Measure how often the local model picks the right tool.

    python eval/tool_selection.py --model gpt-oss:20b
    python eval/tool_selection.py --model qwen3:8b --runs 3
    python eval/tool_selection.py --check      # validate the cases only, no model needed

The tools are NOT executed. Only the model's choice (which tool, which arguments) is recorded,
so nothing is switched on, played or sent. Results are written to eval/results/<model>.json.
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cases import CASES  # noqa: E402


def check_cases() -> None:
    from jarvis import brain

    names = {f.__name__ for f in brain.ALL_TOOLS}
    bad = [c for c in CASES if c[1] is not None and c[1] not in names]
    if bad:
        sys.exit(f"Unknown tool names in cases: {bad}")
    from unittest import mock

    from jarvis import fastlane, tools

    with mock.patch.multiple(tools, **{n: mock.Mock(return_value="ok") for n in names & set(tools.BY_NAME)}):
        handled = [c[0] for c in CASES if fastlane.route(c[0]) is not None]
    if handled:
        sys.exit(f"These cases are answered by the fast lane, so they never reach the model: {handled}")
    print(f"{len(CASES)} cases OK; {sum(c[1] is None for c in CASES)} expect no tool; tools covered: "
          f"{len({c[1] for c in CASES if c[1]})} of {len(names)}")


def run(model: str, runs: int) -> dict:
    import ollama

    from jarvis import brain

    b = brain.Brain()
    system = b._system()
    rows = []
    for text, want_tool, want_arg in CASES:
        for _ in range(runs):
            msgs = [system, {"role": "user", "content": text}]
            t0 = time.time()
            resp = ollama.chat(model=model, messages=msgs, tools=brain.ALL_TOOLS, **brain._think_option(model))
            secs = time.time() - t0
            calls = resp.message.tool_calls or []
            got_tool = calls[0].function.name if calls else None
            got_args = dict(calls[0].function.arguments or {}) if calls else {}
            tool_ok = got_tool == want_tool
            arg_ok = tool_ok and (want_arg is None or want_arg in json.dumps(got_args).lower())
            rows.append({"text": text, "want": want_tool, "got": got_tool, "args": got_args,
                         "tool_ok": tool_ok, "arg_ok": arg_ok, "seconds": round(secs, 2)})
    return {"model": model, "runs": runs, "rows": rows}


def summarise(result: dict) -> str:
    rows = result["rows"]
    n = len(rows)
    tool = sum(r["tool_ok"] for r in rows) / n
    arg = sum(r["arg_ok"] for r in rows) / n
    with_tool = [r for r in rows if r["want"]]
    no_tool = [r for r in rows if not r["want"]]
    secs = [r["seconds"] for r in rows]
    lines = [
        f"Model: {result['model']}   cases: {len(CASES)}   runs each: {result['runs']}",
        f"Right tool or right silence: {tool:.0%}",
        f"Right tool and right arguments: {arg:.0%}",
        f"Tool requests answered correctly: {sum(r['tool_ok'] for r in with_tool) / len(with_tool):.0%}",
        f"Correctly made no tool call: {sum(r['tool_ok'] for r in no_tool) / len(no_tool):.0%}",
        f"Median seconds per request: {statistics.median(secs):.1f}   slowest: {max(secs):.1f}",
        "",
        "Mistakes:",
    ]
    for r in rows:
        if not r["arg_ok"]:
            lines.append(f"  {r['text']!r}: wanted {r['want']}, got {r['got']} {r['args'] if r['got'] else ''}")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check or not a.model:
        check_cases()
        sys.exit(0)
    result = run(a.model, a.runs)
    out = ROOT / "eval" / "results"
    out.mkdir(exist_ok=True)
    (out / (a.model.replace(":", "_").replace("/", "_") + ".json")).write_text(json.dumps(result, indent=2))
    print(summarise(result))
