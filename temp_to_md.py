#!/usr/bin/env python3
"""Render temp.json (chat messages) into a human-readable Markdown file."""
import json

SRC = "/Users/wenwu/work/xiaozhi-esp32-server/temp.json"
OUT = "/Users/wenwu/work/xiaozhi-esp32-server/temp-conversation.md"

with open(SRC, encoding="utf-8") as f:
    messages = json.load(f)

ROLE_LABELS = {
    "system": "System (系统提示)",
    "user": "User (用户)",
    "assistant": "Assistant (助手)",
    "tool": "Tool (工具)",
}

lines = []
lines.append("# Conversation — temp.json")
lines.append("")
lines.append(f"> Rendered from `temp.json` · {len(messages)} messages")
lines.append("")
lines.append("---")
lines.append("")

for i, msg in enumerate(messages, 1):
    role = msg.get("role", "?")
    label = ROLE_LABELS.get(role, role)
    lines.append(f"## {i}. {label}")
    lines.append("")

    # Tool calls
    tool_calls = msg.get("tool_calls")
    if tool_calls:
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "?")
            args = fn.get("arguments", "")
            try:
                args_pretty = json.dumps(json.loads(args), ensure_ascii=False, indent=2)
            except Exception:
                args_pretty = args
            lines.append(f"**Tool call** `{tc.get('id', '?')}` → `{name}`")
            lines.append("")
            lines.append("```json")
            lines.append(args_pretty)
            lines.append("```")
            lines.append("")

    # Tool result — render once inside a long fence (content may contain ```)
    if role == "tool":
        result = msg.get("content") or ""
        lines.append("````")
        lines.append(result.strip())
        lines.append("````")
        lines.append("")
        continue

    # Content (system / user / assistant)
    content = msg.get("content") or ""
    if content:
        lines.append(content.strip())
        lines.append("")

    lines.append("---")
    lines.append("")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"Wrote {OUT} ({len(lines)} lines)")
