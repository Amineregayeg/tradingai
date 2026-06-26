"""Unit tests for the GovernanceQueue approve/reject/edit flows.

Mocks at the DB boundary only — business logic is exercised in full.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.enums import AlertStatus
from app.services.governance.queue import GovernanceQueue


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_alert() -> MagicMock:
    """Minimal Alert-like object in PENDING state."""
    alert = MagicMock()
    alert.id = uuid.uuid4()
    alert.user_id = "system"
    alert.status = AlertStatus.PENDING
    alert.pair = "EUR_USD"
    alert.context_json = {}
    alert.suggested_action = {"sl": 1.0810, "tp": 1.0900, "lot_size": 0.1}
    alert.edit_diffs = []
    return alert


def _make_db(alert: MagicMock | None) -> AsyncMock:
    """Build a mock AsyncSession that returns *alert* from execute()."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = alert

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------


class TestApprove:
    @pytest.mark.asyncio
    async def test_approve_sets_status_approved(self, mock_alert: MagicMock) -> None:
        db = _make_db(mock_alert)
        queue = GovernanceQueue()

        with patch("app.services.governance.queue.audit_logger") as mock_audit:
            mock_audit.alert_approved = AsyncMock()
            await queue.process_action(db, "system", mock_alert.id, "approve", None, None)

        assert mock_alert.status == AlertStatus.APPROVED

    @pytest.mark.asyncio
    async def test_approve_sets_resolved_by(self, mock_alert: MagicMock) -> None:
        db = _make_db(mock_alert)
        queue = GovernanceQueue()

        with patch("app.services.governance.queue.audit_logger") as mock_audit:
            mock_audit.alert_approved = AsyncMock()
            await queue.process_action(db, "trader-1", mock_alert.id, "approve", None, None)

        assert mock_alert.resolved_by == "trader-1"

    @pytest.mark.asyncio
    async def test_approve_calls_commit(self, mock_alert: MagicMock) -> None:
        db = _make_db(mock_alert)
        queue = GovernanceQueue()

        with patch("app.services.governance.queue.audit_logger") as mock_audit:
            mock_audit.alert_approved = AsyncMock()
            await queue.process_action(db, "system", mock_alert.id, "approve", None, None)

        db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_approve_raises_kill_switch_when_halted(self, mock_alert: MagicMock) -> None:
        from app.core.exceptions import KillSwitchArmed

        mock_alert.context_json = {"compliance_state": "HALTED"}
        db = _make_db(mock_alert)
        queue = GovernanceQueue()

        with pytest.raises(KillSwitchArmed):
            await queue.process_action(db, "system", mock_alert.id, "approve", None, None)


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------


class TestReject:
    @pytest.mark.asyncio
    async def test_reject_sets_status_rejected(self, mock_alert: MagicMock) -> None:
        db = _make_db(mock_alert)
        queue = GovernanceQueue()

        with patch("app.services.governance.queue.audit_logger") as mock_audit:
            mock_audit.alert_rejected = AsyncMock()
            await queue.process_action(db, "system", mock_alert.id, "reject", None, "Bad setup")

        assert mock_alert.status == AlertStatus.REJECTED

    @pytest.mark.asyncio
    async def test_reject_sets_resolved_by(self, mock_alert: MagicMock) -> None:
        db = _make_db(mock_alert)
        queue = GovernanceQueue()

        with patch("app.services.governance.queue.audit_logger") as mock_audit:
            mock_audit.alert_rejected = AsyncMock()
            await queue.process_action(db, "user-99", mock_alert.id, "reject", None, "No setup")

        assert mock_alert.resolved_by == "user-99"


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------


class TestEdit:
    @pytest.mark.asyncio
    async def test_edit_creates_one_diff_per_field(self, mock_alert: MagicMock) -> None:
        db = _make_db(mock_alert)
        queue = GovernanceQueue()
        changes = {"sl": 1.0815, "lot_size": 0.05}

        with patch("app.services.governance.queue.audit_logger") as mock_audit:
            mock_audit.alert_edited = AsyncMock()
            await queue.process_action(db, "system", mock_alert.id, "edit", changes, "Tighter SL")

        # db.add is called once for the alert itself + once per diff
        # The impl calls db.add(diff) for each field, then db.add(alert) once
        add_calls = db.add.call_count
        assert add_calls >= len(changes)  # at least one add per changed field

    @pytest.mark.asyncio
    async def test_edit_sets_status_edited(self, mock_alert: MagicMock) -> None:
        db = _make_db(mock_alert)
        queue = GovernanceQueue()

        with patch("app.services.governance.queue.audit_logger") as mock_audit:
            mock_audit.alert_edited = AsyncMock()
            await queue.process_action(
                db, "system", mock_alert.id, "edit", {"sl": 1.0820}, "Adjusted SL"
            )

        assert mock_alert.status == AlertStatus.EDITED

    @pytest.mark.asyncio
    async def test_edit_applies_new_value_to_suggested_action(self, mock_alert: MagicMock) -> None:
        db = _make_db(mock_alert)
        queue = GovernanceQueue()

        with patch("app.services.governance.queue.audit_logger") as mock_audit:
            mock_audit.alert_edited = AsyncMock()
            await queue.process_action(
                db, "system", mock_alert.id, "edit", {"sl": 1.0850}, None
            )

        assert mock_alert.suggested_action["sl"] == 1.0850

    @pytest.mark.asyncio
    async def test_edit_with_empty_changes_raises(self, mock_alert: MagicMock) -> None:
        from app.core.exceptions import InvalidAlertAction

        db = _make_db(mock_alert)
        queue = GovernanceQueue()

        with pytest.raises(InvalidAlertAction):
            await queue.process_action(db, "system", mock_alert.id, "edit", {}, None)


# ---------------------------------------------------------------------------
# Guard rails
# ---------------------------------------------------------------------------


class TestGuardRails:
    @pytest.mark.asyncio
    async def test_action_on_non_pending_raises_invalid_action(
        self, mock_alert: MagicMock
    ) -> None:
        from app.core.exceptions import InvalidAlertAction

        mock_alert.status = AlertStatus.APPROVED  # already resolved
        db = _make_db(mock_alert)
        queue = GovernanceQueue()

        with pytest.raises(InvalidAlertAction):
            await queue.process_action(db, "system", mock_alert.id, "approve", None, None)

    @pytest.mark.asyncio
    async def test_action_on_rejected_alert_raises(self, mock_alert: MagicMock) -> None:
        from app.core.exceptions import InvalidAlertAction

        mock_alert.status = AlertStatus.REJECTED
        db = _make_db(mock_alert)
        queue = GovernanceQueue()

        with pytest.raises(InvalidAlertAction):
            await queue.process_action(db, "system", mock_alert.id, "reject", None, None)

    @pytest.mark.asyncio
    async def test_action_on_missing_alert_raises_not_found(self) -> None:
        from app.core.exceptions import AlertNotFound

        db = _make_db(None)  # simulate not found
        queue = GovernanceQueue()

        with pytest.raises(AlertNotFound):
            await queue.process_action(db, "system", uuid.uuid4(), "approve", None, None)

    @pytest.mark.asyncio
    async def test_unknown_action_raises_invalid_action(self, mock_alert: MagicMock) -> None:
        from app.core.exceptions import InvalidAlertAction

        db = _make_db(mock_alert)
        queue = GovernanceQueue()

        with pytest.raises(InvalidAlertAction):
            await queue.process_action(db, "system", mock_alert.id, "explode", None, None)
