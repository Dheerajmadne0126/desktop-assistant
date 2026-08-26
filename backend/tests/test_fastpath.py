from app.ai.agent.fastpath import fast_path


def test_open_chrome_english():
    m = fast_path.match("Open Chrome")
    assert m and m.tool_name == "open_application" and m.args["app_name"] == "chrome"


def test_chrome_kholo():
    m = fast_path.match("chrome kholo")
    assert m and m.tool_name == "open_application"


def test_vscode_chalu_kar():
    m = fast_path.match("vscode chalu kar")
    assert m is not None


def test_close_notepad():
    m = fast_path.match("close notepad")
    assert m and m.tool_name == "close_application"


def test_time_query():
    m = fast_path.match("what time is it")
    assert m and m.tool_name == "get_system_time"


def test_screenshot():
    m = fast_path.match("screenshot")
    assert m and m.tool_name == "take_screenshot"


def test_language_preference():
    m = fast_path.match("speak in marathi")
    assert m and m.tool_name == "__set_language__" and m.args["language"] == "Marathi"


def test_remember_fact():
    m = fast_path.match("remember that my favourite colour is black")
    assert m and m.tool_name == "remember_fact"
    assert "black" in m.args["text"]


def test_recall_question():
    m = fast_path.match("what is my favourite colour?")
    assert m and m.tool_name == "recall_information"


def test_conversation_not_matched():
    assert fast_path.match("I'm really hungry today, what should I do about lunch?") is None
    assert fast_path.match("who won the cricket match yesterday") is None
