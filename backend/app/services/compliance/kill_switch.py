"""Kill switch — emergency position closure for prop firm compliance."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ComplianceError
from app.core.kill_switch_state import KILL_SWITCH_STATE, KillSwitchState
from app.core.logging import logger


class KillSwitch:
    """
    arm() → marks armed with optional reason.
    trigger() → arms if not armed, closes all positions, audits, and notifies via WebSocket.

    **THE STATE IS `app.core.kill_switch_state.KILL_SWITCH_STATE`, NOT THIS OBJECT'S** (`B442`, manager's
    ruling 1). Every adapter reads that object at the moment it SENDS, so an entry that passed the loop's
    gate before the switch was pulled is refused at submission. `_armed` and `_reason` were class
    attributes shadowed per instance; they are properties over the shared state now, so there is ONE
    switch per process however many `KillSwitch()` objects exist — an instance with state of its own would
    be a switch no adapter reads.
    """

    def __init__(self, state: KillSwitchState = KILL_SWITCH_STATE) -> None:
        self._state = state

    @property
    def _armed(self) -> bool:
        return self._state.armed

    @property
    def _reason(self) -> str | None:
        return self._state.reason

    def arm(self, reason: str | None = None) -> None:
        """Arm the kill switch (does NOT close positions)."""
        self._state.armed = True
        self._state.reason = reason
        logger.warning("Kill switch ARMED", reason=reason)

    def disarm(self) -> None:
        """Disarm the kill switch — **REFUSED WHILE A TRIGGER IS CLOSING POSITIONS** (review's K2-12, ruled).

        A disarm mid-sweep reopens sends, and `AlpacaAdapter`'s second sweep could then close a position the
        engine had just opened. No production code calls this today; the refusal protects the future caller.
        The mark it reads is cleared in `trigger()`'s `finally`, so a trigger that raised or was cancelled
        never leaves the switch undisarmable (K2-10).
        """
        started = self._state.trigger_started
        if started is not None:
            raise ComplianceError(
                f"the kill switch is still closing positions (a trigger started "
                f"{time.monotonic() - started:.1f}s ago); it can be disarmed after it reports"
            )
        self._state.armed = False
        self._state.reason = None
        logger.info("Kill switch disarmed")

    @property
    def is_armed(self) -> bool:
        return self._state.armed

    @property
    def reason(self) -> str | None:
        return self._state.reason

    async def trigger(
        self,
        db: AsyncSession,
        user_id: str,
        reason: str | None = None,
    ) -> dict:
        """
        Arm (if not already armed), close all positions via broker_manager.close_all_positions(),
        persist an audit log entry, broadcast via ws_manager, send an SMTP alert if configured.

        **A SECOND TRIGGER WHILE ONE IS RUNNING CLOSES NOTHING** (`B443`, manager's item 6). It answers
        *already in progress*, with how long the first has run and the rows reported so far. Without this,
        an operator whose request timed out at the proxy pulls again, and every position gets a second close
        order — a second sell. The check and the mark are set with no `await` between them, and the mark is
        cleared in `finally`: on return, on raise, and on cancellation (K2-10).

        **IT ARMS ITSELF FIRST** (review's K2-11, ruled). Both callers arm before triggering, but a caller
        that only triggered would sweep while sends were still open. Idempotent: an armed switch keeps the
        reason it was armed with.

        **A CANCELLED TRIGGER FINISHES THE SWEEP, AND THEN SAYS IT WAS CANCELLED** (`B446`, manager's ruling). A panic
        stop left half done is the worst state, so the sweep runs as its own task, awaited through
        `asyncio.shield`. It used to be the other way round and silent about it: the adapter turned the
        cancellation into a `BrokerError`, `broker_manager` stepped past it, and this returned normally, so nothing
        awaiting it ever learned it had been cancelled. Now, once the sweep is done, every row is logged, the audit
        row is written in a FRESH session (the caller's will not commit on a cancellation), and `CancelledError`
        is re-raised. **It never returns normally after a cancellation.**

        **STATED COST (manager's ruling 5):** a shutdown waits for the sweep, bounded per adapter by the sweep's own
        bounds — including `B443`'s 100s response deadline for Alpaca's second sweep — and a repeated cancel cannot
        cut it short.

        **THE IN-PROGRESS MARK LIVES AS LONG AS THE SWEEP** (ruling 3), and is cleared in the sweep task's own
        `finally`: a cancelled caller must not let a second trigger start closing while the first still is.

        Returns: {positions_closed, positions_failed_to_close, positions_not_attempted, details, message}, or,
        while another trigger is running, the already-in-progress answer (no counters).
        """
        state = self._state
        if state.trigger_started is not None:
            return self._already_in_progress(user_id, reason)
        state.trigger_started = time.monotonic()
        state.trigger_started_at = datetime.now(timezone.utc).isoformat()
        outcome: dict = {}
        try:
            if not state.armed:
                self.arm(reason=reason or "Manual kill switch trigger")
            sweep = asyncio.ensure_future(self._sweep(db, user_id, reason, outcome))
        except BaseException:
            state.trigger_started = None
            state.trigger_started_at = None
            raise

        caller_cancelled = False
        while not sweep.done():
            try:
                await asyncio.shield(sweep)
            except asyncio.CancelledError:
                if sweep.cancelled():
                    break                      # the SWEEP ITSELF was cancelled (a loop shutdown cancels every task)
                if not caller_cancelled:
                    caller_cancelled = True
                    logger.error(
                        "Kill switch trigger CANCELLED while closing positions: FINISHING the sweep, then "
                        "re-raising the cancellation",
                        user_id=user_id, reason=reason,
                    )
            except BaseException:
                # `B453`. THE SWEEP RAISED. With no cancellation that is the trigger's own failure and it propagates, as
                # before, the same object (F-4). AFTER one it must NOT escape from this await: the caller was cancelled
                # and must see `CancelledError`, with the failure logged and audited below. Measured at ab64c03
                # (deployed): it escaped as the sweep's RuntimeError, and the row log and fresh-session audit never ran.
                # A BaseException that is not an Exception (KeyboardInterrupt, SystemExit) still escapes as itself from
                # `sweep.result()` below (S-F2).
                if not caller_cancelled:
                    raise

        if sweep.cancelled():
            self._log_rows("the kill switch's SWEEP was itself CANCELLED; rows reported before it stopped",
                           outcome.get("partial_report"))
            raise asyncio.CancelledError("the kill switch's sweep was cancelled")
        if not caller_cancelled:
            return sweep.result()
        try:
            result = sweep.result()
        except Exception as exc:  # noqa: BLE001 - the caller was cancelled; that is what it must see
            # `B453`. BOTH EXITS land here (review's F-5): a sweep that raised THROUGH the shield after the cancel (caught
            # in the loop above), and a sweep already done with an exception when the cancel landed — which at ab64c03
            # re-raised correctly and still left no audit and no rows. There is no result dict, so the rows are the
            # exception's `partial_report` if it carries one, else what the manager had reported so far; NO COUNTS are
            # invented (F-6, B366).
            from app.services.broker.manager import broker_manager

            failure = f"{type(exc).__name__}: {exc}"
            partial = getattr(exc, "partial_report", None)
            rows = list(partial) if isinstance(partial, list) else broker_manager.close_all_rows_so_far()
            logger.error("Kill switch: the CANCELLED trigger's sweep RAISED; rows reported before it failed follow",
                         error=failure, rows_so_far=len(rows))
            await self._leave_cancelled_record(
                user_id, rows, "the kill switch trigger was CANCELLED and its sweep RAISED; row reported before it failed",
                {"reason": reason or self._reason, "positions_closed": None, "positions_failed_to_close": None,
                 "details": rows, "sweep_failure": failure},
            )
            raise asyncio.CancelledError("the kill switch trigger was cancelled; its sweep raised") from exc
        await self._leave_cancelled_record(
            user_id, result.get("details"), "the kill switch trigger was CANCELLED; the sweep FINISHED with this row", result)
        raise asyncio.CancelledError("the kill switch trigger was cancelled after its sweep finished")

    #: How long a cancelled trigger's audit write may take, SHIELDED from further cancellations (manager's ruling S-F1).
    #: Read LIVE on every write.
    CANCELLED_AUDIT_BOUND_S = 5.0

    async def _leave_cancelled_record(self, user_id: str, rows, context: str, audit: dict) -> None:
        """**The record a CANCELLED trigger leaves, on EVERY cancelled path** (`B446`, `B453`; ruling F-17): the sweep
        finished, the sweep raised through the shield, or the sweep had already raised when the cancel landed. Every row
        at ERROR — or, with none, that the state of every position is UNKNOWN — then the audit row in a FRESH session.

        THE WRITE IS SHIELDED AND BOUNDED (manager's ruling S-F1, review's measurements on 3.12.3): repeated shutdown
        cancellations must not erase the record. ONE deadline is fixed when the write starts; each further cancellation
        is noted and the write is awaited again for what REMAINS of that deadline — never a bound restarted per cancel
        (shape B), never a loop swallowing cancels inside `asyncio.timeout`, which swallows the timeout's own cancel and
        hangs (shape A). On expiry the rows are already at ERROR, the expiry is said, and the write is LEFT RUNNING — it
        may still commit — with a callback that retrieves its outcome, so nothing reaches the loop's exception handler
        (F-16). Never raises; every caller re-raises `CancelledError` after it."""
        self._log_rows(context, rows if rows else None)
        write = asyncio.ensure_future(self._audit_in_fresh_session(user_id, audit))
        loop = asyncio.get_running_loop()
        bound = self.CANCELLED_AUDIT_BOUND_S
        deadline = loop.time() + bound
        while not write.done():
            remaining = deadline - loop.time()
            if remaining <= 0:
                write.add_done_callback(lambda task: task.cancelled() or task.exception())
                logger.error("Kill switch: the CANCELLED trigger's audit write did not finish within its bound; the rows "
                             "above are the record, and the write is left running", bound_s=bound)
                return
            try:
                await asyncio.wait_for(asyncio.shield(write), remaining)
            except asyncio.CancelledError:
                continue          # a further cancellation: noted by the caller's re-raise; the write goes on
            except TimeoutError:
                continue          # the deadline check above says so
            except Exception:  # noqa: BLE001 - _audit_in_fresh_session guards itself; belt and braces
                return

    async def _sweep(self, db: AsyncSession, user_id: str, reason: str | None, outcome: dict) -> dict:
        """The trigger's body as its own task. Clears the in-progress mark when the SWEEP ends, however it ends."""
        try:
            return await self._run_trigger(db, user_id, reason)
        except asyncio.CancelledError as exc:
            outcome["partial_report"] = getattr(exc, "partial_report", None)
            raise
        finally:
            self._state.trigger_started = None
            self._state.trigger_started_at = None

    @staticmethod
    def _log_rows(what: str, rows) -> None:
        """One ERROR line per row, with the row's facts as FIELDS (loguru formats the message; a venue reason carries
        braces). Absent rows are said, not skipped."""
        if not isinstance(rows, list):
            logger.error("Kill switch: NO rows were reported; the state of every open position is UNKNOWN", context=what)
            return
        for row in rows:
            logger.error(
                "Kill switch row", context=what, pair=row.get("pair"), position_id=row.get("position_id"),
                disposition=row.get("disposition"), status=row.get("status"), reason=row.get("reason"),
                error=row.get("error"), broker=row.get("broker"), connection_id=row.get("connection_id"),
            )

    async def _audit_in_fresh_session(self, user_id: str, result: dict) -> None:
        """The audit row for a CANCELLED trigger (manager's ruling 2). The caller's session rolls back on
        `CancelledError` (`get_session` commits only after a normal exit), so the row written during the sweep is
        lost; this writes it again in its own session and commits. A failure is logged and never stops the
        cancellation being re-raised."""
        try:
            from app.db import session as dbsession

            async with dbsession.async_session_maker() as fresh:
                fresh.add(self._audit_entry(user_id, result))
                await fresh.commit()
        except Exception as exc:  # noqa: BLE001
            logger.error("Kill switch: the CANCELLED trigger's audit row could NOT be written",
                         error=f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _audit_entry(user_id: str, result: dict):
        from app.db.enums import ActorType
        from app.models.audit_log import AuditLog

        details = result.get("details") or []
        return AuditLog(
            user_id=user_id,
            event_type="KILL_SWITCH_TRIGGERED",
            entity_type="system",
            entity_id=None,
            actor=ActorType.SYSTEM,
            old_value=None,
            new_value={
                "reason": result.get("reason"),
                "positions_closed": result.get("positions_closed"),
                "positions_failed": result.get("positions_failed_to_close"),
                # `B453`: present only when the sweep of a CANCELLED trigger raised — the audit names the failure
                **({"sweep_failure": result["sweep_failure"]} if result.get("sweep_failure") else {}),
            },
            metadata_json={"details": details[:20]},  # cap details length
            result="HALTED",
        )

    def _already_in_progress(self, user_id: str, reason: str | None) -> dict:
        from app.services.broker.manager import broker_manager

        started = self._state.trigger_started
        elapsed = time.monotonic() - started if started is not None else 0.0
        rows = broker_manager.close_all_rows_so_far()
        logger.warning(
            "Kill switch trigger REFUSED: a trigger is already closing positions",
            user_id=user_id, reason=reason, in_progress_for_s=round(elapsed, 1),
            started_at=self._state.trigger_started_at, rows_so_far=len(rows),
        )
        # NO COUNTERS (manager's ruling on (e)). A `positions_closed: 0` here became the route's trigger response —
        # `B366`'s "0 closed" at the moment an operator is most likely to misread it. The route answers 409.
        return {
            "already_in_progress": True,
            "in_progress_for_s": round(elapsed, 1),
            "details": rows,
            "message": (
                f"Kill switch ALREADY IN PROGRESS: a trigger started {elapsed:.1f}s ago "
                f"({self._state.trigger_started_at}) and has reported {len(rows)} row(s) so far. This request "
                f"closed nothing and sent nothing; the first trigger's report is the one to read."
            ),
        }

    async def _run_trigger(
        self,
        db: AsyncSession,
        user_id: str,
        reason: str | None = None,
    ) -> dict:
        effective_reason = reason or self._reason or "Manual kill switch trigger"
        logger.warning(
            "Kill switch TRIGGERED",
            user_id=user_id,
            reason=effective_reason,
        )

        # Close all positions
        from app.services.broker.base import BrokerAdapter
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
        # READ THE PRODUCERS' CONSTANT, NOT A COPY OF ITS VALUE (`T-0132`). Both adapters write
        # `BrokerAdapter.NOT_ATTEMPTED`; this counted against the string `"NOT_ATTEMPTED"`. **Two
        # sources for one fact is `B184`** — the very thing hoisting the vocabulary to the base
        # class was for, left behind at the consumer. Inert today only because the constant's
        # value equals the literal, **which is exactly why it is worth fixing while nothing
        # depends on the coincidence**: if the value ever changes, both producers change together
        # and this silently disagrees, on the counting path where `B330` already bit once — a
        # NOT_ATTEMPTED row counted as CLOSED and reported to the operator as one.
        not_attempted_rows = [
            r for r in close_results if r.get("disposition") == BrokerAdapter.NOT_ATTEMPTED
        ]
        accounted = [
            r for r in close_results if r.get("disposition") != BrokerAdapter.NOT_ATTEMPTED
        ]

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
            "reason": effective_reason,
            "details": close_results,
            "message": (
                f"Kill switch triggered: {positions_closed} position(s) closed, "
                f"{positions_failed} failed{not_attempted_clause}. Reason: {effective_reason}"
            ),
        }

        # Persist audit log entry
        try:
            db.add(self._audit_entry(user_id, result))
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


kill_switch = KillSwitch(KILL_SWITCH_STATE)
