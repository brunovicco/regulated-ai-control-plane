"""Tests for the server-rendered operator dashboard."""

from datetime import UTC, date, datetime

from regulated_ai.domain import (
    CapabilityState,
    DataClassification,
    ObligationType,
    OperatorAttentionCode,
    OperatorTimeline,
    OperatorTimelineStage,
    OperatorTimelineStageKind,
    ProviderCapabilitySnapshot,
)
from regulated_ai.entrypoints.operator_dashboard import (
    dashboard_headers,
    operator_dashboard_css,
    render_operator_dashboard,
)


def _timeline() -> OperatorTimeline:
    now = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
    return OperatorTimeline(
        enforcement_id="enf_dashboard_test",
        evaluation_id="eval_dashboard_test",
        evidence_id="ev_dashboard_test",
        correlation_id="correlation-dashboard-test",
        policy_set_version="policy@test",
        provider_registry_version="registry@test",
        tool_catalog_version="tools@test",
        classification_labels=(DataClassification.PERSONAL_DIRECT_IDENTIFIER,),
        obligation_types=(ObligationType.REQUIRE_EVIDENCE,),
        matched_policy_ids=("rule@test",),
        provider_capability_ids=("provider.service.control",),
        provider_capability_snapshots=(
            ProviderCapabilitySnapshot(
                capability_id="provider.service.control",
                provider_target='provider.service."><script>alert(1)</script>',
                key="control",
                state=CapabilityState.SUPPORTED,
                conditions=("reviewed",),
                verified_at=date(2026, 9, 22),
                record_version="1",
                registry_version="registry@test",
                source_urls=('https://provider.invalid/?value="><script>',),
            ),
        ),
        provider_context_complete=True,
        control_objective_ids=("CONTROL.TEST",),
        decision_reason_codes=("TEST",),
        enforcement_reason_codes=(),
        authorized_tool_ids=("cards.read@1",),
        provider_target='provider.service."><script>alert(1)</script>',
        transformation_receipts=(),
        approval=None,
        input_digest="sha256:input",
        output_digest="sha256:output",
        event_digest="sha256:event",
        previous_event_digest=None,
        stages=(
            OperatorTimelineStage(
                sequence=1,
                kind=OperatorTimelineStageKind.EVALUATION,
                record_id="ev_dashboard_test",
                created_at=now,
                status="REQUIRE_APPROVAL",
            ),
            OperatorTimelineStage(
                sequence=2,
                kind=OperatorTimelineStageKind.ENFORCEMENT,
                record_id="enf_dashboard_test",
                created_at=now,
                status="WAITING_APPROVAL",
                attention_codes=(OperatorAttentionCode.ENFORCEMENT_APPROVAL_REQUIRED,),
            ),
        ),
        attention_codes=(OperatorAttentionCode.ENFORCEMENT_APPROVAL_REQUIRED,),
    )


def test_operator_dashboard_escapes_all_metadata_and_uses_no_script() -> None:
    html = render_operator_dashboard(_timeline(), enforcement_id="enf_dashboard_test")

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Atenção necessária" in html
    assert "provider.service.control" in html
    assert "actor_id" not in html
    assert "<script src=" not in html


def test_operator_dashboard_security_headers_disallow_active_content() -> None:
    headers = dashboard_headers()

    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    assert "style-src 'self'" in headers["Content-Security-Policy"]
    assert "unsafe-inline" not in headers["Content-Security-Policy"]
    assert operator_dashboard_css()


def test_operator_dashboard_empty_and_error_states_do_not_discover_records() -> None:
    empty = render_operator_dashboard()
    missing = render_operator_dashboard(enforcement_id="enf_missing", error="not_found")

    assert "não lista nem pesquisa registros" in empty
    assert "Timeline não encontrada" in missing
    assert 'value="enf_missing"' in missing
