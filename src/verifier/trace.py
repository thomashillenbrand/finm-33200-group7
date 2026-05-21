"""Pretty-print and persist the agent's reasoning + tool calls.

deepagents (via langgraph) returns a list of LangChain messages. Each is one
of: HumanMessage, AIMessage (may carry tool_calls), ToolMessage (tool result).

Pipeline:
  to_records(result["messages"])  → plain-dict records (one normalization)
  print_trace(records)            → truncated, terminal-friendly stdout
  save_trace(records, phase_name) → untruncated JSON + Markdown to data/traces/

Phase 1 has no agent loop, so it constructs records directly (see its source).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

DIVIDER = "=" * 70
TRACES_DIR = Path(__file__).resolve().parents[2] / "data" / "traces"


def to_records(messages: list[Any]) -> list[dict]:
    """Convert a list of LangChain messages to plain-dict records."""
    records = []
    for msg in messages:
        msg_type = getattr(msg, "type", None) or getattr(msg, "role", "?")
        record: dict = {
            "type": msg_type,
            "content": getattr(msg, "content", "") or "",
        }
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            record["tool_calls"] = [
                {
                    "id": _get(tc, "id"),
                    "name": _get(tc, "name"),
                    "args": _get(tc, "args"),
                }
                for tc in tool_calls
            ]
        if msg_type == "tool":
            record["tool_name"] = getattr(msg, "name", None) or "?"
            record["tool_call_id"] = getattr(msg, "tool_call_id", None)
        records.append(record)
    return records


def print_trace(records: list[dict]) -> None:
    """Walk records and print a clean trace + final answer."""
    if not records:
        print("(empty trace)")
        return

    print(DIVIDER)
    print("AGENT TRACE")
    print(DIVIDER)

    for r in records:
        msg_type = r["type"]
        content = r.get("content", "")
        tool_calls = r.get("tool_calls", [])

        if msg_type == "human":
            print(f"\n[USER]\n{_truncate(str(content), 400)}")
        elif msg_type == "ai":
            if tool_calls:
                for tc in tool_calls:
                    print(f"\n[AGENT → tool] {tc['name']}({_format_args(tc['args'])})")
            elif content:
                print(f"\n[AGENT] {_truncate(str(content), 300)}")
        elif msg_type == "tool":
            print(f"\n[TOOL ← {r.get('tool_name', '?')}]\n{_truncate(str(content), 400)}")
        else:
            print(f"\n[{msg_type}] {_truncate(str(content), 200)}")

    print(f"\n{DIVIDER}")
    print("FINAL ANSWER")
    print(DIVIDER)
    print(records[-1].get("content", ""))


def save_trace(records: list[dict], phase_name: str) -> tuple[Path, Path]:
    """Persist records as JSON + Markdown under data/traces/. Returns the paths."""
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    base = TRACES_DIR / f"{phase_name}_{timestamp}"
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")

    payload = {"phase": phase_name, "timestamp": timestamp, "messages": records}
    json_path.write_text(json.dumps(payload, indent=2, default=str, ensure_ascii=False))
    md_path.write_text(_render_markdown(payload))
    return json_path, md_path


def _render_markdown(payload: dict) -> str:
    lines = [f"# {payload['phase']} — {payload['timestamp']}", ""]
    for r in payload["messages"]:
        msg_type = r["type"]
        content = str(r.get("content", "")).strip()
        tool_calls = r.get("tool_calls", [])

        if msg_type == "human":
            lines += ["## User", "", content, ""]
        elif msg_type == "ai":
            if tool_calls:
                for tc in tool_calls:
                    lines += [f"## Agent → tool: `{tc['name']}({_format_args(tc['args'])})`", ""]
            if content:
                lines += ["## Agent", "", content, ""]
        elif msg_type == "tool":
            lines += [f"## Tool ← `{r.get('tool_name', '?')}`", "", "```", content, "```", ""]
        else:
            lines += [f"## {msg_type}", "", content, ""]
    return "\n".join(lines)


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, "?")
    return getattr(obj, key, "?")


def _format_args(args: Any) -> str:
    if isinstance(args, dict):
        return ", ".join(f"{k}={v!r}" for k, v in args.items())
    return repr(args)


def _truncate(s: str, n: int) -> str:
    s = s.strip()
    return s if len(s) <= n else s[:n] + " ..."
