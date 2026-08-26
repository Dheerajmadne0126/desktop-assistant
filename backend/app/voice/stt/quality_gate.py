import re
from app.voice.stt.base import STTResult

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_VOWELS = set("aeiouAEIOU")
_JARVIS_VARIANT = re.compile(r"jarv|जर्विस|जार्विस|serv[iae]?$", re.I)
_VALID_SHORT_COMMANDS = {
    "hi", "hey", "yes", "no", "ok", "okay", "stop", "pause", "play", "time",
    "haan", "nahi", "ha", "na", "bas", "nako", "thamb", "ruk", "ruko",
}


def stt_quality_gate(result: STTResult) -> tuple[bool, str]:
    """Heuristic gate separating real utterances from noise/music garbage.

    Deliberately permissive for genuine short commands ("open chrome", "yes").
    Returns (accepted, reason).
    """
    text = (result.text or "").strip()
    if len(text) < 2:
        return False, "too_short"

    lowered = text.lower()

    if result.confidence is not None and result.confidence < 0.30:
        return False, f"low_confidence_{result.confidence:.2f}"

    if lowered in _VALID_SHORT_COMMANDS:
        return True, "known_short_command"

    addressed = bool(_JARVIS_VARIANT.search(text))
    if addressed:
        return True, "wake_addressed"

    if result.confidence is not None and result.confidence < 0.35:
        return False, f"low_confidence_{result.confidence:.2f}"

    has_devanagari = bool(_DEVANAGARI.search(text))
    if not has_devanagari:
        letters = [c for c in text if c.isalpha()]
        if letters and not any(c in _VOWELS for c in letters):
            return False, "no_vowels"

        if re.fullmatch(r"[A-Za-z] ?\d+|\d+ ?[A-Za-z]", text):
            return False, "letter_number_noise"

        words = text.split()
        if len(words) == 1 and len(text) <= 3 and lowered not in _VALID_SHORT_COMMANDS:
            return False, "tiny_unknown_token"

        vowel_ratio = sum(1 for c in letters if c in _VOWELS) / max(len(letters), 1)
        if len(letters) >= 8 and vowel_ratio < 0.18:
            return False, "consonant_soup"

    return True, "ok"
