import json

import pytest

from app.conversation.clarifier import clarification_manager


def _ensure_tools():
    from app.tools import register_all_tools

    register_all_tools()


@pytest.mark.needs_db
async def test_slot_fill_completes(fake_llm_factory, monkeypatch):
    _ensure_tools()
    import app.conversation.clarifier as clarifier_module

    llm = fake_llm_factory(
        json.dumps({"extracted": {"filepath": "notes.txt"}, "still_missing": []})
    )
    monkeypatch.setattr(clarifier_module, "get_fast_llm", lambda: llm)

    state = clarification_manager.start(
        conversation_id="c1",
        tool_name="delete_file",
        missing=["filepath"],
        collected={},
    )
    done = await clarification_manager.feed_user_reply(state, "delete notes.txt")
    assert done
    assert state.collected["filepath"] == "notes.txt"
    assert clarification_manager.get("c1") is None


@pytest.mark.needs_db
async def test_partial_fill_asks_again(fake_llm_factory, monkeypatch):
    _ensure_tools()
    import app.conversation.clarifier as clarifier_module

    llm = fake_llm_factory(
        json.dumps({"extracted": {"subject": "hello"}, "still_missing": ["to_address", "body"]})
    )
    monkeypatch.setattr(clarifier_module, "get_fast_llm", lambda: llm)

    state = clarification_manager.start(
        conversation_id="c2", tool_name="send_email", missing=["to_address", "subject", "body"]
    )
    done = await clarification_manager.feed_user_reply(state, "subject is hello")
    assert done == "asked_more"
    question = clarification_manager.question_for(state)
    assert "?" in question


def test_question_template():
    state = clarification_manager.start(
        conversation_id="c3", tool_name="open_application", missing=["app_name"]
    )
    q = clarification_manager.question_for(state)
    assert "application" in q.lower()


def test_round_limit_expires():
    state = clarification_manager.start(
        conversation_id="c4", tool_name="set_reminder", missing=["time"]
    )
    state.rounds = 99
    assert clarification_manager.get("c4") is None
