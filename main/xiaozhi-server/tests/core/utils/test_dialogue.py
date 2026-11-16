"""Tests for the Message/Dialogue classes used to build LLM context."""
import pytest

from core.utils.dialogue import (
    Dialogue,
    Message,
    TOOL_EXAMPLE_PREFIX,
    build_tool_call_fewshot_messages,
)


def test_message_assigns_default_uniq_id():
    m = Message(role="user", content="hi")
    assert m.uniq_id is not None
    assert len(m.uniq_id) > 0


def test_message_preserves_explicit_uniq_id():
    m = Message(role="user", content="hi", uniq_id="abc")
    assert m.uniq_id == "abc"


def test_message_default_is_not_temporary():
    m = Message(role="user", content="hi")
    assert m.is_temporary is False


def test_message_tool_call_id_default_is_none():
    m = Message(role="user", content="hi")
    assert m.tool_call_id is None


def test_dialogue_starts_empty():
    d = Dialogue()
    assert d.dialogue == []


def test_dialogue_put_appends_message():
    d = Dialogue()
    d.put(Message(role="user", content="hi"))
    d.put(Message(role="assistant", content="hello"))
    assert len(d.dialogue) == 2


def test_dialogue_get_llm_dialogue_includes_user_and_assistant():
    d = Dialogue()
    d.put(Message(role="user", content="hi"))
    d.put(Message(role="assistant", content="hello"))
    msgs = d.get_llm_dialogue()
    assert {"role": "user", "content": "hi"} in msgs
    assert {"role": "assistant", "content": "hello"} in msgs


def test_dialogue_update_system_message_replaces_existing():
    d = Dialogue()
    d.update_system_message("you are a helper")
    d.update_system_message("you are a coder")
    system_msgs = [m for m in d.dialogue if m.role == "system"]
    assert len(system_msgs) == 1
    assert system_msgs[0].content == "you are a coder"


def test_dialogue_update_system_message_creates_when_missing():
    d = Dialogue()
    d.update_system_message("you are a coder")
    assert len(d.dialogue) == 1
    assert d.dialogue[0].role == "system"


@pytest.mark.asyncio
async def test_get_llm_dialogue_with_memory_substitutes_into_system_message():
    d = Dialogue()
    d.update_system_message("Memory so far: <memory></memory>")
    msgs = d.get_llm_dialogue_with_memory(memory_str="user likes cats")
    system = next(m for m in msgs if m["role"] == "system")
    assert "user likes cats" in system["content"]
    assert "<memory></memory>" not in system["content"]


@pytest.mark.asyncio
async def test_get_llm_dialogue_separates_temporary_few_shot_from_actual_history():
    d = Dialogue()
    d.put(Message(role="user", content="real user msg", is_temporary=False))
    d.put(Message(role="user", content="fewshot example", is_temporary=True))
    msgs = d.get_llm_dialogue()
    contents = [m["content"] for m in msgs if m["role"] == "user"]
    assert "real user msg" in contents
    assert "fewshot example" in contents


def _fewshot_text(messages):
    """Flatten text and tool-call arguments so tests can search all of it."""
    parts = []
    for message in messages:
        if message.content:
            parts.append(message.content)
        for tool_call in message.tool_calls or []:
            parts.append(tool_call.get("function", {}).get("arguments", ""))
    return " ".join(parts)


def test_tool_call_fewshot_is_temporary_and_marked_as_example():
    messages = build_tool_call_fewshot_messages({"handle_exit_intent"})

    assert messages
    assert all(message.is_temporary for message in messages)

    user_messages = [m for m in messages if m.role == "user"]
    assert user_messages
    assert all(
        m.content.startswith(TOOL_EXAMPLE_PREFIX) for m in user_messages
    )


def test_tool_call_fewshot_has_no_story_or_pending_promise():
    messages = build_tool_call_fewshot_messages({"handle_exit_intent"})
    text = _fewshot_text(messages)

    # Regression guard: the old example ("给我讲个故事吧" → "选一个我给你开讲")
    # made weak models think a story was still pending in the real session.
    assert "故事" not in text
    assert "开讲" not in text


def test_tool_call_fewshot_ends_with_direct_answer():
    messages = build_tool_call_fewshot_messages({"handle_exit_intent"})

    assistant_calls = [m for m in messages if m.tool_calls]
    assert assistant_calls[-1].tool_calls[0]["function"]["name"] == "direct_answer"

    tool_results = [m for m in messages if m.role == "tool"]
    assert tool_results[-1].tool_call_id == "fewshot_da_001"


def test_tool_call_fewshot_keeps_direct_answer_without_exit_tool():
    messages = build_tool_call_fewshot_messages(set())

    assert messages
    called_tools = [
        tool_call["function"]["name"]
        for message in messages
        for tool_call in (message.tool_calls or [])
    ]
    assert called_tools == ["direct_answer"]
