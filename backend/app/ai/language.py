import re

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")

_MARATHI_MARKERS = [
    "आहे", "आहेस", "हवे", "पाहिजे", "काय", "कसे", "कसा", "कुठे", "कधी", "कोण",
    "मला", "तुला", "आम्ही", "तू", "मी", "कर", "करा", "सांग", "दे", "घे", "जा",
    "उघड", "बंद", "नको", "थांब", "धन्यवाद", "नमस्कार", "शुभ", "सकाळ", "संध्याकाळ",
]

_HINDI_MARKERS = [
    "है", "हैं", "चाहिए", "क्या", "कैसे", "कहाँ", "कब", "कौन", "मुझे", "तुम्हें",
    "हम", "तुम", "मैं", "करो", "कर", "बताओ", "दो", "लो", "जाओ", "खोलो", "बंद",
    "मत", "रुको", "धन्यवाद", "नमस्ते", "सुप्रभात", "शुभ", "सुबह", "शाम",
]

_LATIN_MARATHI = [
    "ahe", "aahes", "pahije", "have", "kay", "kasa", "kase", "kuthe", "kadhi", "kon",
    "mala", "tula", "amhi", "nako", "thamb", "sang", "ugad", "udya", "atta", "jhala",
    "jhali", "karu", "karnar", "sangitl", "madhe", "var", "khali", "kiti",
]

_LATIN_HINDI = [
    "hai", "hain", "chahiye", "kya", "kaise", "kahan", "kab", "kaun", "mujhe",
    "tumhe", "hum", "tum", "main", "karo", "batao", "kholo", "mat", "ruko",
    "shukriya", "acha", "accha", "thik", "theek", "kal", "abhi", "kitna",
]

_SHARED_IMPERATIVES = ["kar", "kara"]


def detect_language(text: str) -> str:
    lowered = text.lower().strip()
    if not lowered:
        return "English"

    has_devanagari = bool(_DEVANAGARI.search(text))
    marathi_score = sum(1 for w in _MARATHI_MARKERS if w in text)
    hindi_score = sum(1 for w in _HINDI_MARKERS if w in text)

    latin_marathi = sum(1 for w in _LATIN_MARATHI if re.search(rf"\b{re.escape(w)}\b", lowered))
    latin_hindi = sum(1 for w in _LATIN_HINDI if re.search(rf"\b{re.escape(w)}\b", lowered))

    imperative = sum(
        1 for w in _SHARED_IMPERATIVES if re.search(rf"\b{re.escape(w)}\b", lowered)
    )

    if has_devanagari or marathi_score or latin_marathi or imperative:
        marathi_total = marathi_score + latin_marathi + (2 if has_devanagari else 0)
        hindi_total = hindi_score + latin_hindi
        if marathi_total >= hindi_total:
            return "Marathi"
        return "Hindi"

    if hindi_score or latin_hindi:
        return "Hindi"

    return "English"
