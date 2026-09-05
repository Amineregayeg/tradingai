"""Kill switch — emergency position closure for prop firm compliance."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger


class KillSwitch:
    """
    In-memory kill switch state.
    arm() → marks armed with optional reason.
    trigger() → closes all positions, audits, and notifies via WebSocket.
    """

    _armed: bool = False
    _reason: str | None = None

    def arm(self, reason: str | None = None) -> None:
        """Arm the kill switch (does NOT close positions)."""
        self._armed = True
        self._reason = reason
        logger.warning("Kill switch ARMED", reason=reason)

    def disarm(self) -> None:
        """Disarm the kill switch."""
        self._armed = False
        self._reason = None
        logger.info("Kill switch disarmed")

    @property
    def is_armed(self) -> bool:
        return self._armed

    @property
    def reason(self) -> str | None:
        return self._reason

    async def trigger(
        self,
        db: AsyncSession,
        user_id: str,
        reason: str | None = None,
    ) -> dict:
        """
        Close all positions via broker_manager.close_all_positions().
        Persist audit log entry.
        Broadcast kill_switch_triggered via ws_manager.
        Send SMTP alert if configured.

        Returns: {positions_closed, positions_failed_to_close, details, message}
        """
        effective_reason = reason or self._reason or "Manual kill switch trigger"
        logger.warning(
            "Kill switch TRIGGERED",
            user_id=user_id,
            reason=effective_reason,
        )

        # Close all positions
        from app.services.broker.manager import broker_manager

        try:
            close_results = await broker_manager.close_all_positions()
        except Exception as exc:
            # `B366`. **THE REPORT IS ALREADY ON THE EXCEPTION AND THIS USED TO DROP IT.**
            #
            # `close_all_positions` publishes its rows BEFORE the loop runs and attaches them to
            # the error it re-raises, precisely so a partial record survives an abnormal exit
            # (`B303`). The consumer then set `close_results = []`, so the operator was told
            # **"0 closed, 0 failed"** while a complete four-row report sat on the exception that
            # had just been discarded. The ruled property held at the adapter and died at the
            # boundary — and *nothing was closed* and *we lost the record of what was* are the
            # same sentence to whoever reads the alert at 3am.
            #
            # Nothing new is needed to fix it: the data is produced three lines away.
            partial = getattr(exc, "partial_report", None)
            close_results = list(partial) if partial else []
            logger.error(
                "Kill switch: error calling close_all_positions",
                error=str(exc),
                partial_rows_recovered=len(close_results),
            )
            if not close_results:
                # NO REPORT AT ALL IS A DIFFERENT STATE FROM AN EMPTY BOOK, and the counters below
                # cannot express it — they would read 0/0/0, which is what a flat account looks
                # like. Said here so it is not inferred from three zeros.
                logger.error(
                    "Kill switch: close_all_positions failed and carried NO partial report, so "
                    "the state of every open position is UNKNOWN — this is not an empty book"
                )

        # ------------------------------------------------------------------
        # THREE STATES, NOT TWO — `B330`, and Malek ruled the property on 2026-08-31:
        #
        #   Every position open when the switch was pulled must be reported as CLOSED,
        #   FAILED WITH A REASON, or NOT ATTEMPTED.
        #
        # THIS COUNT USED TO DEFEAT THAT RULING AT THE LAST STEP. `positions_closed` was
        # `status not in ("error", "failed")`, so a row saying NOBODY REACHED THIS POSITION was
        # counted as a position successfully CLOSED — on the control whose entire purpose is to
        # leave nothing open. **That is worse than an error, because an error prompts a look and
        # a closed-count does not.**
        #
        # A row without a `disposition` is one of the older shapes that cannot express the third
        # state; it keeps exactly its previous meaning, so this widens the vocabulary without
        # reinterpreting any adapter that has not adopted it.
        not_attempted_rows = [r for r in close_results if r.get("disposition") == "NOT_ATTEMPTED"]
        accounted = [r for r in close_results if r.get("disposition") != "NOT_ATTEMPTED"]

        positions_closed = sum(
            1 for r in accounted if r.get("status") not in ("error", "failed")
        )
        positions_failed = sum(
            1 for r in accounted if r.get("status") in ("error", "failed")
        )
        positions_not_attempted = len(not_attempted_rows)

        # NAMED IN THE OPERATOR'S MESSAGE, not only in the payload. The number a human reads at
        # 3am is this sentence, and a third state that appears only in `details` is a third state
        # nobody sees.
        not_attempted_clause = (
            f", {positions_not_attempted} NOT ATTEMPTED (still open)"
            if positions_not_attempted else ""
        )

        result = {
            "positions_closed": positions_closed,
            "positions_failed_to_close": positions_failed,
            "positions_not_attempted": positions_not_attempted,
            "details": close_results,
            "message": (
                f"Kill switch triggered: {positions_closed} position(s) closed, "
                f"{positions_failed} failed{not_attempted_clause}. Reason: {effective_reason}"
            ),
        }

        # Persist audit log entry
        try:
            from app.db.enums import ActorType
            from app.models.audit_log import AuditLog

            audit_entry = AuditLog(
                user_id=user_id,
                event_type="KILL_SWITCH_TRIGGERED",
                entity_type="system",
                entity_id=None,
                actor=ActorType.SYSTEM,
                old_value=None,
                new_value={
                    "reason": effective_reason,
                    "positions_closed": positions_closed,
                    "positions_failed": positions_failed,
                },
                metadata_json={"details": close_results[:20]},  # cap details length
                result="HALTED",
            )
            db.add(audit_entry)
            await db.flush()
        except Exception as exc:
            logger.error("Kill switch: failed to write audit log", error=str(exc))

        # Broadcast via WebSocket
        try:
            from app.services.ws.manager import ws_manager

            await ws_manager.push_kill_switch(
                profile_id="system",
                reason=effective_reason,
                positions_closed=positions_closed,
                positions_failed=positions_failed,
            )
        except Exception as exc:
            logger.error("Kill switch: failed to push WS event", error=str(exc))

        # SMTP alert (best-effort, non-blocking)
        try:
            await _send_smtp_alert(effective_reason, positions_closed, positions_failed)
        except Exception as exc:
            logger.warning("Kill switch: SMTP alert failed", error=str(exc))

        logger.warning(
            "Kill switch complete",
            positions_closed=positions_closed,
            positions_failed=positions_failed,
            reason=effective_reason,
        )

        return result


async def _send_smtp_alert(
    reason: str,
    positions_closed: int,
    positions_failed: int,
) -> None:
    """Send SMTP email alert if SMTP is configured."""
    from app.config import settings

    if not settings.smtp_host or not settings.smtp_from:
        return  # SMTP not configured

    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = "[Trading AI Co-Pilot] KILL SWITCH TRIGGERED"
    msg["From"] = settings.smtp_from
    msg["To"] = settings.smtp_from  # send to self for single-tenant

    timestamp = datetime.now(timezone.utc).isoformat()
    msg.set_content(
        f"Kill switch triggered at {timestamp}.\n\n"
        f"Reason: {reason}\n"
        f"Positions closed: {positions_closed}\n"
        f"Positions failed to close: {positions_failed}\n\n"
        f"All trading has been halted. Please review your account immediately."
    )

    import asyncio

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _smtp_send_sync, msg, settings)


def _smtp_send_sync(msg, settings) -> None:  # type: ignore[no-untyped-def]
    """Synchronous SMTP send, run in executor."""
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        server.starttls()
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)
    logger.info("Kill switch SMTP alert sent")


kill_switch = KillSwitch()
