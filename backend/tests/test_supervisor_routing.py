import json
from types import SimpleNamespace

import pytest

from app.ai.agent import supervisor as supervisor_module
from app.ai.agent.supervisor import supervisor


@pytest.fixture(autouse=True)
def _ensure_registry():
    from app.tools import register_all_tools

    register_all_tools()


def tool_call(name, args):
    return {"name": name, "args": args}


def llm_msg(content="", tool_calls=None):
    return {"content": content, "tool_calls": tool_calls or []}


def _patch_llms(monkeypatch, fake_llm_factory, main_items, fast_items=()):
    main = fake_llm_factory(*main_items)
    fast = fake_llm_factory(*fast_items)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **kw: fast)
    monkeypatch.setattr(supervisor_module, "get_llm", lambda **kw: main)
    return main, fast


@pytest.mark.needs_db
async def test_chat_single_call(fake_llm_factory, monkeypatch):
    _patch_llms(
        monkeypatch,
        fake_llm_factory,
        main_items=["I hear you, hungry already? Want me to find a place?"],
    )
    result = await supervisor.process_user_input("I am really hungry today")
    assert result.mode == "chat"
    assert "hungry" in result.reply


@pytest.mark.needs_db
async def test_tool_call_executes_with_template_reply(fake_llm_factory, monkeypatch):
    captured = {}

    async def fake_execute(name, args, **kwargs):
        captured["name"] = name
        captured["args"] = dict(args)

        from app.tools.base import ToolResult

        return ToolResult(success=True, message=f"Opened {args.get('app_name')}.")

    monkeypatch.setattr(supervisor_module.registry, "execute", fake_execute)

    _patch_llms(
        monkeypatch,
        fake_llm_factory,
        main_items=[llm_msg(tool_calls=[tool_call("open_application", {"app_name": "chrome"})])],
    )
    result = await supervisor.process_user_input("please launch chrome browser for me")
    assert captured["name"] == "open_application"
    assert captured["args"]["app_name"] == "chrome"
    assert result.mode == "tool"
    assert "chrome" in result.reply.lower()
    assert "<think" not in result.reply.lower()


@pytest.mark.needs_db
async def test_missing_arg_starts_clarification_then_asks_more(fake_llm_factory, monkeypatch):
    import json as _json

    _patch_llms(
        monkeypatch,
        fake_llm_factory,
        main_items=[llm_msg(tool_calls=[tool_call("send_email", {})])],
        fast_items=[
            _json.dumps({"extracted": {"to_address": "ravi@gmail.com"}, "still_missing": ["subject", "body"]})
        ],
    )
    first = await supervisor.process_user_input("send an email for me")
    assert first.mode == "clarify"

    second = await supervisor.process_user_input("to ravi at gmail dot com")
    assert second.mode in ("clarify", "tool")


@pytest.mark.needs_db
async def test_confirmation_flow_blocks_until_yes(fake_llm_factory, monkeypatch):
    from app.tools.base import Permission, Tool, ToolResult

    executed = {}

    def do_wipe(filepath: str) -> str:
        executed["filepath"] = filepath
        return f"Wiped {filepath}"

    tool = Tool(
        name="wipe_test_file",
        description="wipes",
        func=do_wipe,
        permission=Permission.CONFIRM,
        confirm_verb="permanently wipe a test file",
    )
    from app.tools.registry import registry

    if registry.get("wipe_test_file") is None:
        registry.register(tool)

    async def real_execute(name, args, triggered_by="agent", conversation_id=None, skip_permission=False):
        t = registry.get(name)
        if t and t.permission == Permission.CONFIRM and not skip_permission:
            from app.services.confirmation import confirmation_service

            pending = await confirmation_service.create_pending(t, args, conversation_id)
            return ToolResult(
                success=False,
                message=f"CONFIRMATION_REQUIRED:{pending.spoken_code}:{t.confirm_verb}",
            )
        return ToolResult(success=True, message=t.func(**args))

    monkeypatch.setattr(registry, "execute", real_execute)

    _patch_llms(
        monkeypatch,
        fake_llm_factory,
        main_items=[
            llm_msg(tool_calls=[tool_call("wipe_test_file", {"filepath": "notes.txt"})]),
            llm_msg(),
        ],
    )
    first = await supervisor.process_user_input("wipe the test file now")
    assert first.mode == "confirm"
    assert "filepath" not in executed

    second = await supervisor.process_user_input("yes")
    assert second.mode == "confirmation"
    assert executed.get("filepath") == "notes.txt"


@pytest.mark.needs_db
async def test_greeting_fastpath_skips_llm(fake_llm_factory, monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("LLM must not be called for bare greetings")

    monkeypatch.setattr(supervisor_module, "get_llm", _boom)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _boom)

    result = await supervisor.process_user_input("Hey Jarvis")
    assert result.mode == "greeting"
    assert result.reply and len(result.reply) > 3


@pytest.mark.needs_db
async def test_multi_tool_routes_to_agentic_then_chat_fallback(fake_llm_factory, monkeypatch):
    msg = llm_msg(
        content="Let me plan this out.",
        tool_calls=[
            tool_call("web_search", {"query": "a"}),
            tool_call("web_search", {"query": "b"}),
        ],
    )
    _patch_llms(monkeypatch, fake_llm_factory, main_items=[msg])

    async def empty_goal(goal, conv_id=None, history=None):
        return None

    monkeypatch.setattr(supervisor_module, "execute_agentic_goal", empty_goal)
    result = await supervisor.process_user_input("research two things and compare them")
    assert result.mode == "chat"


@pytest.mark.needs_db
async def test_empty_reply_retries_plain_chat_not_dead_fallback(fake_llm_factory, monkeypatch):
    _patch_llms(
        monkeypatch,
        fake_llm_factory,
        main_items=[
            llm_msg(),
            "नमस्कार सर! मी जर्विस — सांगा, काय मदत करू?",
        ],
    )
    result = await supervisor.process_user_input("काय मदत आहे?")
    assert result.mode == "chat"
    assert "सर" in result.reply
    assert result.reply.strip() != "I'm here."


@pytest.mark.needs_db
async def test_natural_fallback_when_everything_fails(fake_llm_factory, monkeypatch):
    _patch_llms(
        monkeypatch,
        fake_llm_factory,
        main_items=[llm_msg(), ""],
    )
    result = await supervisor.process_user_input("काय मदत आहे?")
    assert result.mode == "chat"
    assert result.reply != "I'm here."
    assert any(w in result.reply for w in ("सर", "सांगा", "ऐकतोय", "माफ"))


@pytest.mark.needs_db
async def test_language_persistence_after_two_marathi_turns(fake_llm_factory, monkeypatch):
    from app.memory.service import memory_service

    await memory_service.set_preference("reply_language", "auto")

    _patch_llms(
        monkeypatch,
        fake_llm_factory,
        main_items=["हो नक्की सर, आता आपण मराठीत बोलू.", "तुमच्याशीच बोलतोय सर"],
    )
    await supervisor.process_user_input("चला आता मराठीत बोलूया")
    await supervisor.process_user_input("काय करतोयस तू?")

    pref = await memory_service.get_preference("reply_language")
    assert pref == "Marathi"
