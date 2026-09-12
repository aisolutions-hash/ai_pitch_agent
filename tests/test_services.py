from sales_fastapi.services import classify_contact, infer_domain, infer_intent


def test_infer_domain():
    assert infer_domain("info@mahindraaccelo.com") == "mahindraaccelo.com"
    assert infer_domain("no-at-sign") == ""


def test_infer_intent_keywords():
    assert infer_intent("We need procurement of sheet metal") == "procurement"
    assert infer_intent("Hiring SCM manager") == "hiring"
    assert infer_intent("Request for quotation") == "sales"
    assert infer_intent("hello there") == "general"


def test_classify_contact_full():
    verdict = classify_contact("info@mahindraaccelo.com", "SCM procurement Supa MIDC")
    assert verdict["domain"] == "mahindraaccelo.com"
    assert verdict["intent"] == "procurement"
    assert verdict["context"] == "SCM procurement Supa MIDC"


def test_classify_free_email_still_returns_domain():
    verdict = classify_contact("person@gmail.com", "just saying hi")
    assert verdict["domain"] == "gmail.com"
    assert verdict["intent"] == "general"
