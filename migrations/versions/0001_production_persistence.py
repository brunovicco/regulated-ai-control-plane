"""Create transactional production persistence.

Revision ID: 0001_production_persistence
Revises:
Create Date: 2026-09-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_production_persistence"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create metadata-only state, authority and append-only lifecycle tables."""
    op.execute(
        """
        CREATE TABLE evidence (
            evidence_id TEXT PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            correlation_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            policy_set_version TEXT NOT NULL,
            provider_registry_version TEXT NOT NULL,
            matched_policy_ids TEXT NOT NULL,
            provider_capability_ids TEXT NOT NULL,
            control_objective_ids TEXT NOT NULL,
            obligation_types TEXT NOT NULL,
            classification_labels TEXT NOT NULL,
            reason_codes TEXT NOT NULL,
            input_digest TEXT NOT NULL,
            output_digest TEXT NOT NULL,
            event_digest TEXT NOT NULL,
            previous_event_digest TEXT,
            tool_catalog_version TEXT,
            authorized_tool_ids TEXT NOT NULL DEFAULT '[]',
            provider_capability_snapshots TEXT NOT NULL DEFAULT '[]'
        );

        CREATE TABLE enforcement (
            enforcement_id TEXT PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            evaluation_id TEXT NOT NULL,
            evaluation_evidence_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            status TEXT NOT NULL,
            policy_set_version TEXT NOT NULL,
            provider_registry_version TEXT NOT NULL,
            provider_target TEXT NOT NULL,
            transformation_receipts TEXT NOT NULL,
            reason_codes TEXT NOT NULL,
            input_digest TEXT NOT NULL,
            output_digest TEXT,
            provider_execution_id TEXT,
            provider_call_metadata TEXT,
            approval_receipt TEXT,
            tool_proposals TEXT NOT NULL DEFAULT '[]'
        );

        CREATE TABLE tool_action (
            action_id TEXT PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            enforcement_id TEXT NOT NULL,
            evaluation_id TEXT NOT NULL,
            call_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            tool_schema_version TEXT NOT NULL,
            tool_schema_digest TEXT NOT NULL,
            arguments_digest TEXT NOT NULL,
            workload_identity TEXT NOT NULL,
            idempotency_key_digest TEXT NOT NULL,
            action_digest TEXT NOT NULL,
            status TEXT NOT NULL,
            approval_receipt TEXT,
            tool_execution_id TEXT,
            output_digest TEXT,
            output_schema_digest TEXT,
            safe_output_digest TEXT,
            result_classifications TEXT NOT NULL DEFAULT '[]',
            exposed_result_fields TEXT NOT NULL DEFAULT '[]',
            reconciliation_receipt TEXT,
            UNIQUE (enforcement_id, call_id)
        );

        CREATE TABLE approval_consumption (
            approval_id TEXT PRIMARY KEY,
            actor_id TEXT NOT NULL,
            decision_digest TEXT NOT NULL,
            enforcement_id TEXT NOT NULL,
            issued_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ NOT NULL
        );

        CREATE TABLE action_approval_consumption (
            approval_id TEXT PRIMARY KEY,
            actor_id TEXT NOT NULL,
            action_digest TEXT NOT NULL,
            action_id TEXT NOT NULL,
            issued_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ NOT NULL
        );

        CREATE TABLE tool_action_reconciliation_consumption (
            reconciliation_id TEXT PRIMARY KEY,
            actor_id TEXT NOT NULL,
            action_digest TEXT NOT NULL,
            action_id TEXT NOT NULL UNIQUE,
            outcome TEXT NOT NULL CHECK (outcome IN ('EXECUTED','NOT_EXECUTED')),
            tool_execution_id TEXT,
            issued_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ NOT NULL,
            CHECK ((outcome='EXECUTED' AND tool_execution_id IS NOT NULL)
                OR (outcome='NOT_EXECUTED' AND tool_execution_id IS NULL))
        );

        CREATE TABLE operator_lifecycle_event (
            event_sequence BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            recorded_at TIMESTAMPTZ NOT NULL,
            source TEXT NOT NULL CHECK (source IN ('TRANSITION','MIGRATION_BASELINE')),
            entity_kind TEXT NOT NULL CHECK (
                entity_kind IN ('EVALUATION','ENFORCEMENT','TOOL_ACTION')
            ),
            entity_id TEXT NOT NULL,
            enforcement_id TEXT,
            status TEXT NOT NULL,
            UNIQUE (entity_kind, entity_id, status)
        );
        CREATE INDEX idx_operator_lifecycle_enforcement
            ON operator_lifecycle_event (enforcement_id, event_sequence);

        CREATE FUNCTION regulaai_record_lifecycle() RETURNS trigger AS $$
        DECLARE
            event_kind TEXT;
            linked_enforcement TEXT;
            record_identifier TEXT;
            event_time TIMESTAMPTZ;
            event_status TEXT;
        BEGIN
            IF TG_TABLE_NAME = 'evidence' THEN
                event_kind := 'EVALUATION';
                linked_enforcement := NULL;
                record_identifier := NEW.evidence_id;
                event_time := NEW.created_at;
                event_status := NEW.decision;
            ELSIF TG_TABLE_NAME = 'enforcement' THEN
                event_kind := 'ENFORCEMENT';
                linked_enforcement := NEW.enforcement_id;
                record_identifier := NEW.enforcement_id;
                event_time := CASE
                    WHEN TG_OP='INSERT' THEN NEW.created_at ELSE clock_timestamp()
                END;
                event_status := NEW.status;
            ELSE
                event_kind := 'TOOL_ACTION';
                linked_enforcement := NEW.enforcement_id;
                record_identifier := NEW.action_id;
                event_time := CASE
                    WHEN TG_OP='INSERT' THEN NEW.created_at ELSE clock_timestamp()
                END;
                event_status := NEW.status;
            END IF;
            INSERT INTO operator_lifecycle_event (
                recorded_at, source, entity_kind, entity_id, enforcement_id, status
            ) VALUES (
                event_time, 'TRANSITION', event_kind, record_identifier,
                linked_enforcement, event_status
            ) ON CONFLICT (entity_kind, entity_id, status) DO NOTHING;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER evidence_lifecycle_insert
            AFTER INSERT ON evidence FOR EACH ROW EXECUTE FUNCTION regulaai_record_lifecycle();
        CREATE TRIGGER enforcement_lifecycle_insert
            AFTER INSERT ON enforcement FOR EACH ROW EXECUTE FUNCTION regulaai_record_lifecycle();
        CREATE TRIGGER enforcement_lifecycle_status_update
            AFTER UPDATE OF status ON enforcement FOR EACH ROW
            WHEN (OLD.status IS DISTINCT FROM NEW.status)
            EXECUTE FUNCTION regulaai_record_lifecycle();
        CREATE TRIGGER tool_action_lifecycle_insert
            AFTER INSERT ON tool_action FOR EACH ROW EXECUTE FUNCTION regulaai_record_lifecycle();
        CREATE TRIGGER tool_action_lifecycle_status_update
            AFTER UPDATE OF status ON tool_action FOR EACH ROW
            WHEN (OLD.status IS DISTINCT FROM NEW.status)
            EXECUTE FUNCTION regulaai_record_lifecycle();

        CREATE FUNCTION regulaai_reject_lifecycle_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'operator lifecycle events are append-only';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER operator_lifecycle_event_no_update
            BEFORE UPDATE ON operator_lifecycle_event FOR EACH ROW
            EXECUTE FUNCTION regulaai_reject_lifecycle_mutation();
        CREATE TRIGGER operator_lifecycle_event_no_delete
            BEFORE DELETE ON operator_lifecycle_event FOR EACH ROW
            EXECUTE FUNCTION regulaai_reject_lifecycle_mutation();
        """
    )


def downgrade() -> None:
    """Remove the PostgreSQL persistence schema."""
    op.execute(
        """
        DROP TABLE IF EXISTS operator_lifecycle_event;
        DROP FUNCTION IF EXISTS regulaai_reject_lifecycle_mutation();
        DROP TABLE IF EXISTS tool_action_reconciliation_consumption;
        DROP TABLE IF EXISTS action_approval_consumption;
        DROP TABLE IF EXISTS approval_consumption;
        DROP TABLE IF EXISTS tool_action;
        DROP TABLE IF EXISTS enforcement;
        DROP TABLE IF EXISTS evidence;
        DROP FUNCTION IF EXISTS regulaai_record_lifecycle();
        """
    )
