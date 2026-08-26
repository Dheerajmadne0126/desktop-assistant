import re

_THINK_BLOCK_RE = re.compile(r"<think\b.*?</think\s*>", re.DOTALL | re.IGNORECASE)


def clean_llm_text(text) -> str:
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)
    cleaned = _THINK_BLOCK_RE.sub("", text)
    think_pos = cleaned.lower().find("<think")
    if think_pos != -1:
        cleaned = cleaned[:think_pos]
    return cleaned.strip()
