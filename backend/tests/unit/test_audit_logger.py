"""Unit tests for the append-only AuditLogger.

Key invariants:
  1. Every log call inserts exactly one AuditLog row (db.add).
  2. No UPDATE or DELETE statements are ever emitted.
  3. Exceptions are swallowed — audit failures must never break calling code.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.enums import ActorType
from app.models.audit_log import AuditLog
from app.services.audit.logger import AuditLogger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(add_side_effect: Exception | None = None) -> AsyncMock:
    db = AsyncMock()
    if add_side_effect is not None:
        db.add = MagicMock(side_effect=add_side_effect)
    else:
        db.add = MagicMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# TestAuditLoggerInsertBehaviour
# ---------------------------------------------------------------------------


class TestAuditLoggerInsertBehaviour:
    @pytest.mark.asyncio
    async def test_log_calls_db_add(self) -> None:
        svc = AuditLogger()
        db = _make_db()

        await svc.log(
            db,
            "system",
            "ALERT_GENERATED",
            "alert",
            ActorType.SYSTEM,
            entity_id=uuid.uuid4(),
            result="SUCCESS",
        )

        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_inserts_audit_log_instance(self) -> None:
        svc = AuditLogger()
        db = _make_db()

        await svc.log(
            db,
            "system",
            "ALERT_GENERATED",
            "alert",
            ActorType.SYSTEM,
        )

        added_obj = db.add.call_args[0][0]
        assert isinstance(added_obj, AuditLog)

    @pytest.mark.asyncio
    async def test_log_sets_event_type(self) -> None:
        svc = AuditLogger()
        db = _make_db()

        await svc.log(db, "system", "TEST_EVENT", "test_entity", ActorType.AI)

        added_obj = db.add.call_args[0][0]
        assert added_obj.event_type == "TEST_EVENT"

    @pytest.mark.asyncio
    async def test_log_sets_entity_type(self) -> None:
        svc = AuditLogger()
        db = _make_db()

        await svc.log(db, "system", "BROKER_CONNECTED", "broker_connection", ActorType.TRADER)

        added_obj = db.add.call_args[0][0]
        assert added_obj.entity_type == "broker_connection"

    @pytest.mark.asyncio
    async def test_log_sets_user_id(self) -> None:
        svc = AuditLogger()
        db = _make_db()

        await svc.log(db, "trader-42", "TEST", "test", ActorType.TRADER)

        added_obj = db.add.call_args[0][0]
        assert added_obj.user_id == "trader-42"

    @pytest.mark.asyncio
    async def test_log_calls_commit(self) -> None:
        svc = AuditLogger()
        db = _make_db()

        await svc.log(db, "system", "TEST", "test", ActorType.SYSTEM)

        db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_log_propagates_result_field(self) -> None:
        svc = AuditLogger()
        db = _make_db()

        await svc.log(db, "system", "AI_SKIPPED", "ai_analysis", ActorType.SYSTEM, result="SKIPPED")

        added_obj = db.add.call_args[0][0]
        assert added_obj.result == "SKIPPED"

    @pytest.mark.asyncio
    async def test_log_stores_entity_id(self) -> None:
        svc = AuditLogger()
        db = _make_db()
        eid = uuid.uuid4()

        await svc.log(db, "system", "TEST", "test", ActorType.SYSTEM, entity_id=eid)

        added_obj = db.add.call_args[0][0]
        assert added_obj.entity_id == eid


# ---------------------------------------------------------------------------
# TestAuditLoggerAppendOnly (no UPDATE or DELETE)
# ---------------------------------------------------------------------------


class TestAuditLoggerAppendOnly:
    @pytest.mark.asyncio
    async def test_log_never_calls_execute_with_update(self) -> None:
        """db.execute must not be called with any UPDATE statement."""
        svc = AuditLogger()
        db = _make_db()

        await svc.log(db, "system", "TEST", "test", ActorType.SYSTEM)

        for call in db.execute.call_args_list:
            stmt = call[0][0] if call[0] else None
            if stmt is not None:
                stmt_str = str(stmt).upper()
                assert "UPDATE" not in stmt_str
                assert "DELETE" not in stmt_str

    @pytest.mark.asyncio
    async def test_log_never_calls_execute_at_all(self) -> None:
        """The current impl uses db.add+commit, never db.execute."""
        svc = AuditLogger()
        db = _make_db()

        await svc.log(db, "system", "TEST", "test", ActorType.SYSTEM)

        db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# TestAuditLoggerFaultTolerance
# ---------------------------------------------------------------------------


class TestAuditLoggerFaultTolerance:
    @pytest.mark.asyncio
    async def test_swallows_db_add_exception(self) -> None:
        """A DB failure on add must not propagate to the caller."""
        svc = AuditLogger()
        db = _make_db(add_side_effect=Exception("DB connection lost"))

        # Must not raise
        await svc.log(db, "system", "TEST", "test", ActorType.SYSTEM)

    @pytest.mark.asyncio
    async def test_swallows_commit_exception(self) -> None:
        """A DB failure on commit must not propagate to the caller."""
        svc = AuditLogger()
        db = _make_db()
        db.commit = AsyncMock(side_effect=Exception("commit failed"))

        # Must not raise
        await svc.log(db, "system", "TEST", "test", ActorType.SYSTEM)

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self) -> None:
        svc = AuditLogger()
        db = _make_db(add_side_effect=RuntimeError("unexpected"))

        result = await svc.log(db, "system", "TEST", "test", ActorType.SYSTEM)
        assert result is None


# ---------------------------------------------------------------------------
# TestConvenienceMethods
# ---------------------------------------------------------------------------


class TestConvenienceMethods:
    """Verify each named convenience method delegates to log() with the right event_type."""

    def _alert_mock(self) -> MagicMock:
        alert = MagicMock()
        alert.id = uuid.uuid4()
        alert.pair = "EUR_USD"
        alert.type = MagicMock()
        alert.type.value = "ENTRY_SIGNAL"
        alert.priority = MagicMock()
        alert.priority.value = "SUGGESTION"
        alert.score = None
        alert.message = "Test alert"
        return alert

    @pytest.mark.asyncio
    async def test_alert_generated_uses_correct_event_type(self) -> None:
        svc = AuditLogger()
        db = _make_db()
        await svc.alert_generated(db, "system", self._alert_mock())
        added = db.add.call_args[0][0]
        assert added.event_type == "ALERT_GENERATED"

    @pytest.mark.asyncio
    async def test_alert_approved_uses_correct_event_type(self) -> None:
        svc = AuditLogger()
        db = _make_db()
        await svc.alert_approved(db, "system", self._alert_mock())
        added = db.add.call_args[0][0]
        assert added.event_type == "SUGGESTION_APPROVED"

    @pytest.mark.asyncio
    async def test_alert_rejected_uses_correct_event_type(self) -> None:
        svc = AuditLogger()
        db = _make_db()
        await svc.alert_rejected(db, "system", self._alert_mock(), reason="No setup")
        added = db.add.call_args[0][0]
        assert added.event_type == "SUGGESTION_REJECTED"

    @pytest.mark.asyncio
    async def test_alert_edited_uses_correct_event_type(self) -> None:
        svc = AuditLogger()
        db = _make_db()
        await svc.alert_edited(db, "system", self._alert_mock(), diffs=[{"field_path": "sl"}])
        added = db.add.call_args[0][0]
        assert added.event_type == "SUGGESTION_EDITED"

    @pytest.mark.asyncio
    async def test_ai_skipped_uses_correct_event_type(self) -> None:
        svc = AuditLogger()
        db = _make_db()
        await svc.ai_skipped(db, "system", reason="budget_exceeded")
        added = db.add.call_args[0][0]
        assert added.event_type == "AI_SKIPPED"

    @pytest.mark.asyncio
    async def test_kill_switch_triggered_uses_correct_event_type(self) -> None:
        svc = AuditLogger()
        db = _make_db()
        await svc.kill_switch_triggered(db, "system", "prof-123", positions_closed=2)
        added = db.add.call_args[0][0]
        assert added.event_type == "KILL_SWITCH_TRIGGERED"
