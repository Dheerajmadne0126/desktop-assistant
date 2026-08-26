from app.ai.text_utils import clean_llm_text


def test_paired_block_removed():
    assert clean_llm_text("<think>reasoning here</think>\nHello sir") == "Hello sir"


def test_unclosed_block_removed():
    assert clean_llm_text("<think>\nline one\nline two no closing") == ""


def test_leading_newline_before_think():
    assert (
        clean_llm_text("\n<think>\nsome reasoning\nthat never closes") == ""
    )


def test_normal_text_untouched():
    assert clean_llm_text("Just a normal reply.") == "Just a normal reply."


def test_multiple_blocks():
    out = clean_llm_text("<think>a</think>A<think>b</think>B")
    assert out == "AB"
