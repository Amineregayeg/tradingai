"""BrokerManager — singleton that owns all live broker adapter instances."""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BrokerConnectionError, BrokerError
from app.core.logging import logger
from app.core.security import decrypt_credentials, encrypt_credentials
from app.models.broker_connection import BrokerConnection
from app.schemas.broker import BrokerConnectRequest, BrokerConnectionRead, Position
from app.services.broker.base import BrokerAdapter
from app.services.broker.cryptofundtrader import CryptoFundTraderAdapter

_CFT_ALIASES = {"cryptofundtrader", "cft", "match-trader", "matchtrader"}
_MT5_ALIASES = {"mt5", "metatrader5", "metatrader", "metaapi"}


def _make_adapter(
    broker: str,
    creds: dict,
    account_id: str,
    environment: str,
) -> BrokerAdapter:
    """Factory: return the correct adapter for *broker*.

    The OANDA branch was removed: this app is crypto-only and OANDA was the only
    unguarded real-money path. Only CryptoFundTrader (crypto prop firm) is
    constructible here, and it is created observe-only unless live trading is
    explicitly enabled server-side.
    """
    key = broker.lower()

    # ------------------------------------------------------------------------------
    # THE LIVE-TRADING GUARD, HOISTED OUT OF THE CFT BRANCH (`T-0134`).
    #
    # A stored observe_only=False is honoured ONLY when ALLOW_LIVE_TRADING is set
    # server-side. Its own comment said it "runs on EVERY construction path", and that
    # was true only while CFT was the ONLY branch: a second branch returning before this
    # point would have been a new unguarded real-money path, which is exactly why OANDA
    # was deleted from this function. So it now runs BEFORE the dispatch, for every
    # broker, and adding a branch cannot skip it by construction rather than by care.
    # ------------------------------------------------------------------------------
    allow_live = os.getenv("ALLOW_LIVE_TRADING", "false").strip().lower() == "true"
    observe_only = creds.get("observe_only", True)
    if observe_only is False and not allow_live:
        logger.warning(
            "Forcing observe_only=True for stored connection — live trading disabled",
            broker=broker,
        )
        observe_only = True

    if key in _CFT_ALIASES:
        common = dict(
            email=creds.get("email", ""),
            password=creds.get("password", ""),
            base_url=creds.get("base_url", creds.get("server", "")),
            account_id=account_id,
            environment=environment,
            observe_only=observe_only,
        )

        # CFT sits behind Cloudflare bot protection that fingerprints the TLS
        # handshake, so direct HTTP is refused (403) even with a valid token —
        # see cft_bridge_transport for the measurements. When a bridge is
        # configured, route through it; the two adapters are otherwise identical
        # (CFTBridgeAdapter subclasses this one and swaps only the transport).
        if os.getenv("CFT_BRIDGE_TOKEN"):
            from app.services.broker.cft_bridge_adapter import CFTBridgeAdapter

            logger.info("Using browser bridge for Crypto Fund Trader")
            return CFTBridgeAdapter(**common)

        # No bridge configured: the direct adapter. It will almost certainly be
        # blocked by Cloudflare, but it stays the default so behaviour does not
        # change silently for anyone who has not deployed the bridge, and so the
        # existing adapter tests keep exercising the path they were written for.
        return CryptoFundTraderAdapter(**common)

    if key in _MT5_ALIASES:
        # MT5 THROUGH METAAPI — READS ONLY, AND THAT IS NOT A LIMITATION OF THIS BRANCH.
        #
        # `B350`, WHICH CORRECTS `B346`'s MECHANISM WHILE KEEPING ITS CONCLUSION. There are two
        # `place_order` call sites and **both DO reach a `BrokerAdapter`** — `PaperBroker` and
        # `SimPropFirmBroker` are subclasses that define it. The path does not stop short of an
        # adapter; it terminates in one every time, and **the one it terminates in is always
        # SIMULATED and hardcoded at the construction site.** So constructing this adapter puts
        # MT5 on the READ path and on no order path at all. Three further refusals sit behind
        # that: `ExecMode` has no LIVE member, `execute()` raises on `is_simulation=False`, and
        # this adapter's `place_order` refuses outright (`B302`).
        #
        # THIS COMMENT CITED `B346` AND WENT STALE IN THE MINUTE IT WAS WRITTEN. `B350` landed at
        # `c00170b`, immediately after the commit carrying this branch — the citation was accurate
        # when written and wrong when first read. **Nothing links a register id quoted in product
        # code to the entry it names.** The register has amendments and a hook that refuses a
        # commit touching an entry its message does not name; a comment quoting an entry has
        # neither. It matters here because this is the sentence a reader will consult when Gate 4
        # is built, and the wrong mechanism would send them to BUILD an order path that exists.
        #
        # The guard above has already run. It cannot be skipped by returning here, which is the
        # property that made hoisting it a prerequisite for this branch rather than a tidy-up.
        # `observe_only` is not passed on because the adapter has no such parameter and no write
        # to gate — its writes refuse unconditionally. It is logged so the decision is visible
        # rather than silently absent.
        logger.info(
            "Constructing MT5 adapter (reads only; place_order refuses — B302/B346)",
            broker=broker, observe_only=observe_only, allow_live=allow_live,
        )

        # ------------------------------------------------------------------------------
        # WHERE THE METAAPI TOKEN COMES FROM — DECIDED AND RECORDED (`B360`).
        #
        # `T-0134` required this to be *"decided and recorded — a security property, not a style
        # choice"*, and it was decided HERE and written down NOWHERE. A DONE marker closed a
        # half-met requirement, so the decision existed only as the behaviour of this line.
        #
        # **THE TOKEN COMES FROM THE CONNECTION ROW'S ENCRYPTED CREDENTIAL BLOB, AND FROM NOWHERE
        # ELSE. No environment variable is consulted** — `METAAPI_TOKEN` appears nowhere in
        # `backend/app`, and that absence is deliberate rather than an omission.
        #
        # WHY THE BLOB AND NOT AN ENV VAR, since an env var is the obvious alternative and is how
        # `ALLOW_LIVE_TRADING` and `CFT_BRIDGE_TOKEN` above are done:
        #
        #   * **An env var is process-global and a token is per-connection.** The manager holds
        #     many connections and is built to; one variable can hold exactly one account's token,
        #     so a second MT5 account would silently authenticate as the first.
        #   * **The blob is already encrypted at rest** and read through `decrypt_credentials`.
        #     An env var puts a live broker credential in the process environment, where it is
        #     visible to `/proc`, to a crash dump, and to anything that logs `os.environ`.
        #   * **Two sources for one fact is `B184`.** If both were consulted, precedence would
        #     become a security question answered by an `or`.
        #
        # The contrast with the two env vars above is deliberate and not an inconsistency:
        # `ALLOW_LIVE_TRADING` is a SERVER-WIDE POLICY SWITCH that must not be settable from a
        # database row a user can write, and `CFT_BRIDGE_TOKEN` addresses one process-level
        # service. **A per-account credential is the opposite shape.**
        #
        # `api_token` is accepted as a fallback KEY within the same blob — not a second source —
        # because connection rows predating MT5 use that name.
        # ------------------------------------------------------------------------------
        token = creds.get("token", creds.get("api_token", ""))
        if not token:
            raise BrokerConnectionError(
                "MT5 needs a MetaApi token and none was stored. Refusing to construct an adapter "
                "that would fail at the first call with something less specific.",
                broker=broker,
            )
        mt5_account_id = creds.get("mt5_account_id", account_id)
        if not mt5_account_id:
            raise BrokerConnectionError(
                "MT5 needs a MetaApi ACCOUNT ID — the provisioned account's id, which is not the "
                "broker login. Refusing to construct without it.",
                broker=broker,
            )

        def _account_factory():
            """Built here and resolved in `connect()`, which is the async boundary.

            **The SDK is imported INSIDE this closure on purpose** (`B328`): `mt5.py` must stay
            importable in an image without `metaapi_cloud_sdk`, or the contract arm's discovery
            walk skips the adapter in silence. Importing at module scope here would defeat that
            through the factory instead of through the adapter.
            """
            from metaapi_cloud_sdk import MetaApi

            async def _build():
                api = MetaApi(token)
                return await api.metatrader_account_api.get_account(mt5_account_id)

            return _build()

        from app.services.broker.mt5 import MetaTrader5Adapter

        return MetaTrader5Adapter(account=_account_factory, account_id=str(mt5_account_id))

    raise ValueError(f"Unsupported broker: {broker!r}")


def _looks_like_uuid(key: str) -> bool:
    """True for a connection-id key, False for a registered alias like "paper".

    ``register_adapter`` lets the live loop register its PaperBroker under a
    plain name. Reconcile must never evict those: they have no DB row, so a
    naive "not in the wanted set -> drop it" would take the engine's own broker
    away mid-run.
    """
    try:
        uuid.UUID(key)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


class BrokerManager:
    """Singleton manager that holds live broker adapter instances."""

    def __init__(self) -> None:
        # Maps connection_id (str UUID) → adapter instance
        self._adapters: dict[str, BrokerAdapter] = {}
        # Consecutive reconnect failures per connection, and a tick counter, so
        # reconcile_connections() can back off instead of retrying a
        # long-dead broker every single minute.
        self._reconnect_failures: dict[str, int] = {}
        self._reconnect_ticks: int = 0
        self._price_stream_tasks: list[asyncio.Task] = []
        self._price_callback: Callable | None = None

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def load_from_db(self, db: AsyncSession) -> None:
        """Called at startup — load all connected BrokerConnections and init adapters."""
        stmt = select(BrokerConnection).where(BrokerConnection.connected.is_(True))
        result = await db.execute(stmt)
        connections = result.scalars().all()

        logger.info("Loading broker connections from DB", count=len(connections))

        for conn in connections:
            try:
                creds_json = decrypt_credentials(conn.encrypted_creds)
                creds = json.loads(creds_json)
                adapter = _make_adapter(
                    broker=conn.broker,
                    creds=creds,
                    account_id=conn.account_id or "",
                    environment=conn.environment or "practice",
                )
                await adapter.connect()
                self._adapters[str(conn.id)] = adapter
                logger.info(
                    "Broker adapter loaded",
                    broker=conn.broker,
                    connection_id=str(conn.id),
                )
            except Exception as exc:
                # DO NOT write connected=False here.
                #
                # That flag is the DESIRED state — "this connection should be
                # live" — and it is the only record of the user's intent. A
                # deliberate disconnect writes it too (disconnect_broker), so
                # clearing it on a transient failure makes the two
                # indistinguishable, and nothing can tell "the user turned this
                # off" from "this broke and should be retried".
                #
                # That ambiguity was the real cause of a silent outage: the api
                # is ready ~1.4s after start while the cft-bridge needs ~2 min
                # (pip install + Chromium), so on a host reboot the api asks
                # before the bridge can answer, fails once, erased the intent,
                # and never tried again. The dashboard then showed no broker at
                # all rather than an error.
                #
                # Leaving the flag alone lets reconcile_connections() retry.
                # Actual reachability is reported separately and live by
                # get_all_accounts().
                logger.warning(
                    "Broker failed to connect on startup — will retry in background",
                    connection_id=str(conn.id),
                    broker=conn.broker,
                    error=str(exc),
                )

        await db.commit()

    # ------------------------------------------------------------------
    # Connect / disconnect
    # ------------------------------------------------------------------

    async def connect_broker(
        self,
        db: AsyncSession,
        user_id: str,
        request: BrokerConnectRequest,
    ) -> BrokerConnection:
        """Create or update a BrokerConnection, connect, and return the model.

        Steps:
        1. Encrypt raw credentials and persist to DB (connected=False).
        2. Build and connect the adapter (raises BrokerConnectionError on failure).
        3. On success: mark connected=True and store adapter.
        """
        # `B368`. REFUSE AT THE BOUNDARY, BEFORE ANYTHING IS PERSISTED. Step 1 below encrypts and
        # writes the row and step 2 builds the adapter, so a request missing these would leave a
        # connection row behind and fail afterwards. The factory's messages are specific and are
        # reused verbatim rather than paraphrased into a second wording of the same rule.
        if request.broker.lower() in _MT5_ALIASES:
            if not (request.token or "").strip():
                raise BrokerConnectionError(
                    "MT5 needs a MetaApi token and none was supplied. It goes in `token` — NOT "
                    "in `api_key`, which means an exchange API key on every other broker here.",
                    broker=request.broker,
                )
            if not (request.mt5_account_id or request.account_id or "").strip():
                raise BrokerConnectionError(
                    "MT5 needs a MetaApi ACCOUNT ID — the provisioned account's id, which is not "
                    "the broker login. Supply `mt5_account_id`.",
                    broker=request.broker,
                )

        creds_dict: dict = {
            "api_key": request.api_key,
            "api_secret": request.api_secret or "",
        }
        # `B368`. THE ONLY BLOB THAT WORKS USED TO BE ONE THIS METHOD COULD NOT WRITE. `_make_adapter`
        # reads `token` and `mt5_account_id`, and neither was ever put here — so an MT5 connection
        # could be created ONLY by writing the `broker_connections` row straight into the database.
        # It survived two audits because both tested that the ADAPTER ACCEPTS a correct blob and
        # neither tested that the API can EMIT one, with a hand-built blob standing in for the
        # producer both times (`B356`'s axis, one layer out).
        if request.token:
            creds_dict["token"] = request.token
        if request.mt5_account_id:
            creds_dict["mt5_account_id"] = request.mt5_account_id
        # Match-Trader / Crypto Fund Trader style credentials (email + password + base URL).
        if request.email:
            creds_dict["email"] = request.email
        if request.password:
            creds_dict["password"] = request.password
        if request.server:
            creds_dict["base_url"] = request.server
        # SAFETY: an explicit observe_only=False from the API would enable
        # real-money trading. Honour it ONLY when live trading is explicitly
        # enabled server-side (env ALLOW_LIVE_TRADING=true, default OFF), which
        # the public API cannot set. Otherwise force observe-only.
        requested_observe = request.observe_only
        allow_live = os.getenv("ALLOW_LIVE_TRADING", "false").strip().lower() == "true"
        if requested_observe is False and not allow_live:
            logger.warning(
                "Ignoring observe_only=False — live trading is disabled server-side "
                "(set ALLOW_LIVE_TRADING=true to enable). Forcing observe-only.",
                broker=request.broker,
            )
            creds_dict["observe_only"] = True
        elif requested_observe is not None:
            creds_dict["observe_only"] = requested_observe
        creds_json = json.dumps(creds_dict)
        encrypted = encrypt_credentials(creds_json)

        # Check for an existing connection for this user + broker + account_id
        stmt = select(BrokerConnection).where(
            BrokerConnection.user_id == user_id,
            BrokerConnection.broker == request.broker,
            BrokerConnection.account_id == request.account_id,
        )
        result = await db.execute(stmt)
        conn: BrokerConnection | None = result.scalar_one_or_none()

        if conn is None:
            conn = BrokerConnection(
                user_id=user_id,
                broker=request.broker,
                label=request.label,
                encrypted_creds=encrypted,
                account_id=request.account_id,
                environment=request.environment,
                connected=False,
            )
            db.add(conn)
            await db.flush()  # get the generated ID
        else:
            conn.encrypted_creds = encrypted
            conn.label = request.label or conn.label
            conn.environment = request.environment
            conn.connected = False
            db.add(conn)
            await db.flush()

        # Disconnect existing adapter for this connection if any
        existing = self._adapters.pop(str(conn.id), None)
        if existing:
            try:
                await existing.disconnect()
            except Exception:
                pass

        # Build and connect adapter
        adapter = _make_adapter(
            broker=request.broker,
            creds=creds_dict,
            account_id=request.account_id,
            environment=request.environment,
        )

        try:
            await adapter.connect()
        except BrokerConnectionError:
            await db.commit()
            raise
        except Exception as exc:
            await db.commit()
            raise BrokerConnectionError(
                f"Unexpected error connecting to {request.broker}",
                broker=request.broker,
                detail=str(exc),
            ) from exc

        # Success — update DB
        conn.connected = True
        conn.last_connected_at = datetime.now(tz=timezone.utc)
        db.add(conn)
        await db.commit()

        self._adapters[str(conn.id)] = adapter
        logger.info(
            "Broker connected",
            broker=request.broker,
            connection_id=str(conn.id),
            account_id=request.account_id,
        )
        return conn

    async def disconnect_broker(self, db: AsyncSession, connection_id: str) -> None:
        """Disconnect an adapter and mark the DB row as disconnected."""
        adapter = self._adapters.pop(connection_id, None)
        if adapter:
            try:
                await adapter.disconnect()
            except Exception as exc:
                logger.warning("Error disconnecting adapter", connection_id=connection_id, error=str(exc))

        stmt = select(BrokerConnection).where(
            BrokerConnection.id == uuid.UUID(connection_id)
        )
        result = await db.execute(stmt)
        conn = result.scalar_one_or_none()
        if conn:
            conn.connected = False
            db.add(conn)
            await db.commit()

        logger.info("Broker disconnected", connection_id=connection_id)

    async def reconnect_broker(
        self,
        db: AsyncSession,
        connection_id: str,
        user_id: str,
    ) -> BrokerConnection:
        """Re-connect an existing BrokerConnection by its ID."""
        stmt = select(BrokerConnection).where(
            BrokerConnection.id == uuid.UUID(connection_id),
            BrokerConnection.user_id == user_id,
        )
        result = await db.execute(stmt)
        conn = result.scalar_one_or_none()

        if conn is None:
            raise BrokerError(
                f"BrokerConnection {connection_id} not found",
                broker="unknown",
            )

        # Disconnect existing adapter
        existing = self._adapters.pop(connection_id, None)
        if existing:
            try:
                await existing.disconnect()
            except Exception:
                pass

        creds_json = decrypt_credentials(conn.encrypted_creds)
        creds = json.loads(creds_json)

        adapter = _make_adapter(
            broker=conn.broker,
            creds=creds,
            account_id=conn.account_id or "",
            environment=conn.environment or "practice",
        )

        try:
            await adapter.connect()
        except BrokerConnectionError:
            conn.connected = False
            db.add(conn)
            await db.commit()
            raise

        conn.connected = True
        conn.last_connected_at = datetime.now(tz=timezone.utc)
        db.add(conn)
        await db.commit()

        self._adapters[connection_id] = adapter
        logger.info("Broker reconnected", connection_id=connection_id, broker=conn.broker)
        return conn

    # ------------------------------------------------------------------
    # Aggregate operations
    # ------------------------------------------------------------------

    async def get_all_positions_report(self) -> dict:
        """Positions, PLUS the adapters that could not be asked and why (`B372`, `T-0111`).

        **THE PROPERTY, registered by review before this was written:** *every connected adapter is
        accounted for in every aggregate read — either its positions are included, or it is named
        as unasked with a reason. A caller must never be unable to tell a flat book from an unread
        one.*

        `get_all_positions` returned `list[Position]` and swallowed every adapter failure, so three
        different states of the world produced byte-identical output:

            healthy + a broker that CANNOT BE ASKED   -> ['a1', 'a2']
            healthy + a broker that is FLAT           -> ['a1', 'a2']
            healthy, second broker ABSENT entirely    -> ['a1', 'a2']

        **There is no value in a list that means *one of these brokers could not be asked*** — the
        adapter layer's own argument, one level up. The adapter now raises honestly and this layer
        caught, logged at WARNING, and continued.

        **THE SHAPE IS `close_all_positions`' REPORT, NOT THE ADAPTER'S EXCEPTION**, and that
        distinction is review's rather than mine. The adapter expresses *could-not-ask* by raising;
        **this layer cannot raise**, because the endpoint's contract is *never an error* and three
        consumers rest on it. What transfers is the report: one row per subject, an explicit
        disposition, a reason — **per ADAPTER rather than per position.** Third venue for that
        shape this week.

        **`except Exception` STILL CATCHES MORE THAN UNREACHABILITY**, and that is deliberate here:
        review found the defect partly because an invalid `Position` construction inside an adapter
        was swallowed by this same handler and became a silently short list. Narrowing the catch
        would let such a bug crash the aggregate; naming the adapter in `unasked` reports it
        instead, which is the honest form of the same tolerance.
        """
        all_positions: list[Position] = []
        unasked: list[dict] = []
        for connection_id, adapter in self._adapters.items():
            try:
                positions = await adapter.get_positions()
                all_positions.extend(positions)
            except Exception as exc:  # noqa: BLE001 - see the docstring: breadth is deliberate
                unasked.append({
                    "connection_id": connection_id,
                    "broker": adapter.broker_name,
                    "reason": f"{type(exc).__name__}: {exc}",
                })
                logger.warning(
                    "Failed to fetch positions",
                    connection_id=connection_id,
                    broker=adapter.broker_name,
                    error=str(exc),
                )
        return {
            "positions": all_positions,
            "unasked": unasked,
            "asked": len(self._adapters) - len(unasked),
            "connected": len(self._adapters),
        }

    async def get_all_positions(self) -> list[Position]:
        """Aggregate open positions across all connected adapters.

        **Kept returning a bare list on purpose.** Three consumers rest on this signature and on
        its never-raises contract; `get_all_positions_report` is where the unasked adapters are
        readable. A caller that needs to tell a flat book from an unread one must use the report —
        and `positions.py` now does.
        """
        return (await self.get_all_positions_report())["positions"]

    async def reconcile_connections(self, db: AsyncSession) -> dict:
        """Bring reality back in line with intent. Safe to call repeatedly.

        For every connection the user wants live (``connected=True``) that has no
        working adapter, try to establish one. This is what makes a failed
        startup temporary rather than permanent — see the comment in
        ``load_from_db`` for how a transient failure used to become a silent,
        indefinite outage.

        Also drops adapters whose row was deleted, so a removed connection does
        not keep answering from memory.

        Returns a summary for logging. Never raises: this runs on a scheduler,
        and a supervisor that dies on the first error supervises nothing.
        """
        summary = {"checked": 0, "recovered": 0, "still_failing": 0, "dropped": 0}
        try:
            stmt = select(BrokerConnection).where(BrokerConnection.connected.is_(True))
            wanted = list((await db.execute(stmt)).scalars().all())
        except Exception as exc:  # noqa: BLE001 - DB blip must not kill the job
            logger.warning("Reconcile could not read connections", error=str(exc))
            return summary

        wanted_ids = {str(c.id) for c in wanted}

        # Adapters with no surviving row (deleted connection). Skip keys that are
        # not connection ids — the live loop registers its PaperBroker under the
        # literal key "paper", and evicting that would take the engine's own
        # broker out from under it.
        for key in list(self._adapters):
            if key in wanted_ids or not _looks_like_uuid(key):
                continue
            logger.info("Dropping adapter for a deleted connection", connection_id=key)
            adapter = self._adapters.pop(key, None)
            summary["dropped"] += 1
            if adapter is not None:
                try:
                    await adapter.disconnect()
                except Exception:  # noqa: BLE001 - best effort
                    pass

        for conn in wanted:
            cid = str(conn.id)
            summary["checked"] += 1
            if cid in self._adapters:
                continue  # already live; health is reported by get_all_accounts()

            # Back off after repeated failures so a broker that is down for
            # hours does not produce a login attempt every minute — each CFT
            # attempt can cost the bridge an ~11s browser login.
            fails = self._reconnect_failures.get(cid, 0)
            if fails and (self._reconnect_ticks % min(2 ** min(fails, 5), 32)) != 0:
                summary["still_failing"] += 1
                continue

            try:
                # Must mirror load_from_db exactly: decrypt THEN parse. The
                # decrypted blob is JSON text, not a dict.
                creds = json.loads(decrypt_credentials(conn.encrypted_creds))
                adapter = _make_adapter(
                    broker=conn.broker,
                    creds=creds,
                    account_id=conn.account_id or "",
                    environment=conn.environment or "live",
                )
                await adapter.connect()
                self._adapters[cid] = adapter
                self._reconnect_failures.pop(cid, None)
                summary["recovered"] += 1
                logger.info(
                    "Broker connection recovered",
                    connection_id=cid, broker=conn.broker,
                )
            except Exception as exc:  # noqa: BLE001 - keep trying next tick
                self._reconnect_failures[cid] = fails + 1
                summary["still_failing"] += 1
                # First failure at INFO, thereafter DEBUG-ish volume via count:
                # a broker down for a day should not write 1440 warnings.
                if fails == 0:
                    logger.warning(
                        "Broker still unreachable — will keep retrying",
                        connection_id=cid, broker=conn.broker, error=str(exc),
                    )

        self._reconnect_ticks += 1
        return summary

    async def reconcile_all(self, db: AsyncSession, user_id: str = "system") -> list[dict]:
        """Reconcile every connected broker. Read-only; never raises.

        Reports disagreements between our records and the broker's. It
        deliberately does not correct them — see services/broker/reconciliation.py
        for why a reconciler that auto-fixes destroys the evidence it exists to
        surface.
        """
        from app.services.broker.reconciliation import reconcile_broker

        out: list[dict] = []
        for connection_id, adapter in self._adapters.items():
            # Skip the engine's own PaperBroker: it is not a third party whose
            # records could disagree with ours, it IS our records. Reconciling a
            # simulation against itself would produce noise, not signal.
            if getattr(adapter, "is_simulation", False):
                continue
            try:
                report = await reconcile_broker(adapter, db, user_id)
                out.append({"connection_id": connection_id, **report.as_dict()})
            except Exception as exc:  # noqa: BLE001 - one broker must not hide others
                logger.warning(
                    "Reconciliation failed",
                    connection_id=connection_id,
                    broker=getattr(adapter, "broker_name", "?"),
                    error=str(exc),
                )
                out.append({
                    "connection_id": connection_id,
                    "broker": getattr(adapter, "broker_name", "?"),
                    "reachable": False, "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "findings": [], "finding_count": 0,
                })
        return out

    async def get_all_accounts(self) -> list[dict]:
        """Account summary + reachability for every connected adapter.

        One entry per adapter, ALWAYS — a broker that cannot be reached returns
        ``reachable: False`` with the reason rather than being omitted. A
        disappearing row reads as "no such account"; a row that says "cannot
        reach this account right now" is the truth, and it is the difference
        between a dashboard you can trust and one you cannot.

        Never raises. This feeds a status surface, and a status endpoint that
        500s when one broker is down tells you nothing about the others.
        """
        out: list[dict] = []
        for connection_id, adapter in self._adapters.items():
            entry: dict = {
                "connection_id": connection_id,
                "broker": adapter.broker_name,
                "is_simulation": bool(getattr(adapter, "is_simulation", False)),
                # Whether this connection may place orders at all. Surfacing it
                # here means the UI can show, at a glance, that a real-money
                # broker is attached in read-only mode.
                "observe_only": bool(getattr(adapter, "observe_only", True)),
                "reachable": False,
                "account": None,
                "error": None,
            }
            try:
                acct = await adapter.get_account()
                entry["reachable"] = True
                entry["account"] = {
                    "account_id": acct.account_id,
                    "currency": acct.currency,
                    "balance": float(acct.balance),
                    "equity": float(acct.equity),
                    "unrealized_pl": float(acct.unrealized_pl),
                    "margin_used": float(acct.margin_used),
                    "margin_available": float(acct.margin_available),
                    "open_trade_count": int(acct.open_trade_count),
                }
            except Exception as exc:  # noqa: BLE001 - report, never propagate
                entry["error"] = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Failed to fetch account",
                    connection_id=connection_id,
                    broker=adapter.broker_name,
                    error=str(exc),
                )

            # Transport health, where the adapter can report it. For the CFT
            # bridge this distinguishes "the browser session died" from "CFT
            # rejected us" — different problems, different responses.
            probe = getattr(adapter, "bridge_status", None)
            if callable(probe):
                try:
                    entry["transport"] = await probe()
                except Exception as exc:  # noqa: BLE001
                    entry["transport"] = {"reachable": False, "error": str(exc)}

            out.append(entry)
        return out

    async def close_all_positions(self) -> list[dict]:
        """Kill switch: close ALL positions across ALL adapters."""
        results: list[dict] = []
        for connection_id, adapter in self._adapters.items():
            try:
                adapter_results = await adapter.close_all_positions()
                results.extend(adapter_results)
            except Exception as exc:
                logger.error(
                    "Kill switch: error closing positions",
                    connection_id=connection_id,
                    broker=adapter.broker_name,
                    error=str(exc),
                )
                results.append(
                    {
                        "broker": adapter.broker_name,
                        "connection_id": connection_id,
                        "status": "error",
                        "error": str(exc),
                    }
                )
        return results

    # ------------------------------------------------------------------
    # Adapter lookup
    # ------------------------------------------------------------------

    def get_adapter(self, broker: str) -> BrokerAdapter | None:
        """Return the first adapter matching *broker* name (e.g. ``'oanda'``)."""
        for adapter in self._adapters.values():
            if adapter.broker_name.lower() == broker.lower():
                return adapter
        return None

    def get_adapter_by_connection_id(self, connection_id: str) -> BrokerAdapter | None:
        """Return adapter by connection_id string."""
        return self._adapters.get(connection_id)

    def register_adapter(self, key: str, adapter: BrokerAdapter) -> None:
        """Register an externally-owned adapter (e.g. the live loop's in-process
        simulation broker) under a stable string key.

        This replaces the previous private-dict reach-in (``_adapters['paper'] =
        ...``). It is idempotent: registering the same key rebinds it. Used so the
        aggregate position view, the close-routing, and the kill switch all see
        the simulation broker without constructing a second instance.
        """
        self._adapters[key] = adapter
        logger.info("Adapter registered", key=key, broker=adapter.broker_name,
                    is_simulation=adapter.is_simulation)

    # ------------------------------------------------------------------
    # Price streaming
    # ------------------------------------------------------------------

    def set_price_callback(self, callback: Callable) -> None:
        """Register a callback to receive all price ticks."""
        self._price_callback = callback

    async def start_price_streaming(self, pairs: list[str]) -> None:
        """Start streaming prices for *pairs* across all adapters."""
        await self.stop_price_streaming()

        if not self._price_callback:
            logger.warning("No price callback registered — streaming will not forward ticks")

        for connection_id, adapter in self._adapters.items():
            cb = self._price_callback
            # Each adapter streams its own instrument set when it declares one
            # (e.g. a crypto broker streams crypto, not the forex defaults).
            adapter_pairs = adapter.default_pairs or pairs

            async def _stream(adp=adapter, conn_id=connection_id, strm_pairs=adapter_pairs):
                try:
                    await adp.stream_prices(strm_pairs, cb or (lambda _: None))
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    logger.error(
                        "Price stream task error",
                        connection_id=conn_id,
                        broker=adp.broker_name,
                        error=str(exc),
                    )

            task = asyncio.create_task(_stream(), name=f"price_stream_{connection_id}")
            self._price_stream_tasks.append(task)

        logger.info("Price streaming started", adapter_count=len(self._adapters), pairs=pairs)

    async def stop_price_streaming(self) -> None:
        """Cancel all running price stream tasks."""
        for task in self._price_stream_tasks:
            if not task.done():
                task.cancel()
        if self._price_stream_tasks:
            await asyncio.gather(*self._price_stream_tasks, return_exceptions=True)
        self._price_stream_tasks.clear()
        logger.info("Price streaming stopped")

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<BrokerManager adapters={list(self._adapters.keys())}>"


# Module-level singleton
broker_manager = BrokerManager()
