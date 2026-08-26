from app.ai.language import detect_language


def test_english_plain():
    assert detect_language("Open Chrome please") == "English"


def test_marathi_devanagari():
    assert detect_language("मला वाटते तुम्ही नंतर या") in ("Marathi", "Hindi")


def test_hinglish_open_chrome_kar():
    lang = detect_language("Chrome open kar")
    assert lang in ("Marathi", "Hindi")


def test_hinglish_mala_pahije():
    assert detect_language("mala te pahije ahe") == "Marathi"


def test_hinglish_mujhe_chahiye():
    assert detect_language("mujhe woh chahiye") == "Hindi"


def test_empty_defaults_english():
    assert detect_language("") == "English"


def test_numbers_only_english():
    assert detect_language("42") == "English"
