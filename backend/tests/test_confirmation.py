from app.services.confirmation import confirmation_service


def test_code_match_confirms():
    assert confirmation_service.parse_user_response("confirm 1234", "1234") == "confirmed"


def test_plain_yes():
    assert confirmation_service.parse_user_response("yes", "9999") == "confirmed"
    assert confirmation_service.parse_user_response("haan karo", "9999") == "confirmed"


def test_no_denies():
    assert confirmation_service.parse_user_response("no", "9999") == "denied"
    assert confirmation_service.parse_user_response("nahi nako", "9999") == "denied"


def test_unclear():
    assert confirmation_service.parse_user_response("what is it?", "9999") == "unclear"


def test_wrong_digits_not_confirmed():
    assert confirmation_service.parse_user_response("5678", "1234") == "unclear"
