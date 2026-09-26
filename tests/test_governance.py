from sales_fastapi.database import SessionLocal
from sales_fastapi.governance import classification, retention
from sales_fastapi.governance.audit import list_events, log_event
from sales_fastapi.governance.gcp_verify import verify_environment


def test_classification_levels():
    assert classification.classify_field("email") == classification.DataClassification.RESTRICTED
    assert classification.classify_field("password") == classification.DataClassification.RESTRICTED
    assert (
        classification.classify_field("company") == classification.DataClassification.CONFIDENTIAL
    )
    assert classification.classify_field("intent") == classification.DataClassification.INTERNAL
    assert (
        classification.classify_field("something_unknown")
        == classification.DataClassification.INTERNAL
    )


def test_classify_record_uses_max():
    record = {"intent": "sales", "email": "a@b.com"}
    assert classification.classify_record(record) == classification.DataClassification.RESTRICTED


def test_may_leave_environment_blocks_pii():
    assert classification.may_leave_environment("intent") is True
    assert classification.may_leave_environment("email") is False


def test_audit_event_is_persisted_and_redacted():
    db = SessionLocal()
    try:
        event = log_event(
            db,
            action="test.action",
            actor_user_id=42,
            resource_type="contact",
            detail={"email": "person@example.com"},
            commit=True,
        )
        assert event.detail["email"] == "[EMAIL]"
        events = list_events(db, actor_user_id=42)
        assert any(item.action == "test.action" for item in events)
    finally:
        db.close()


def test_retention_purge_dry_run():
    db = SessionLocal()
    try:
        result = retention.purge(db, dry_run=True)
        assert result["dry_run"] is True
        assert "audit_logs" in result["deleted"]
    finally:
        db.close()


def test_gcp_verify_shallow_shape():
    report = verify_environment(deep=False)
    assert set(report["checks"]) == {"project", "adc", "database", "gcs", "secret_manager"}
    assert isinstance(report["ok"], bool)
    # Shallow checks must never surface secret values.
    assert "value" not in report["checks"]["secret_manager"]
