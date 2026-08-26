import pytest

pytestmark = [pytest.mark.needs_db]


async def test_store_and_retrieve_fact_roundtrip():
    from app.memory.service import memory_service

    await memory_service.remember(
        "The user's sister is called Aarti.", category="fact", importance=0.9
    )
    facts = await memory_service.list_fact_texts()
    assert any("Aarti" in f for f in facts)


async def test_preference_set_get():
    from app.memory.service import memory_service

    await memory_service.set_preference("reply_language", "Marathi")
    assert await memory_service.get_preference("reply_language") == "Marathi"
    assert await memory_service.get_preference("missing_key", "default") == "default"
