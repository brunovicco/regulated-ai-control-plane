from datetime import UTC, datetime
from pathlib import Path

from regulated_ai.adapters.evidence_sqlite import SqliteEvidenceRepository
from regulated_ai.domain import (
    DataClassification,
    DecisionOutcome,
    EvidenceMetadata,
    ObligationType,
)


def test_sqlite_round_trip_contains_only_metadata(tmp_path: Path) -> None:
    repository = SqliteEvidenceRepository(tmp_path / "evidence.sqlite3")
    evidence = EvidenceMetadata(
        evidence_id="ev_test",
        created_at=datetime(2026, 9, 23, tzinfo=UTC),
        correlation_id="correlation-test",
        decision=DecisionOutcome.ALLOW_WITH_TRANSFORMATION,
        policy_set_version="policy@1",
        provider_registry_version="registry@1",
        matched_policy_ids=("rule@1",),
        provider_capability_ids=("provider.service.control",),
        control_objective_ids=("CONTROL.TEST",),
        obligation_types=(ObligationType.TOKENIZE,),
        classification_labels=(DataClassification.BRAZIL_CPF,),
        reason_codes=("TEST",),
        input_digest="sha256:input",
        output_digest="sha256:output",
        event_digest="sha256:event",
    )

    stored = repository.save(evidence)
    duplicate = repository.save(evidence)

    assert stored == evidence
    assert duplicate == evidence
    assert repository.get("missing") is None
    assert "raw-sensitive-sentinel" not in (tmp_path / "evidence.sqlite3").read_bytes().decode(
        errors="ignore"
    )
