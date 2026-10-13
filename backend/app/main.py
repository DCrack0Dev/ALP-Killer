"""Secure API surface for the Android client and persistent execution worker."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.broker import BrokerError
from app.config import Settings, get_settings
from app.db import create_database_engine, create_session_factory, get_db, initialize_database
from app.models import (
    AuditEvent,
    AutomationState,
    BacktestRun,
    BrokerConnection,
    Fill,
    Instrument,
    KillSwitchState,
    MarketRegime,
    PnLSnapshot,
    PositionSnapshot,
    RiskConfiguration,
    Signal,
    StrategyConfig,
    SystemHealthEvent,
    User,
    utcnow,
)
from app.schemas import (
    AccountSummary,
    AutomationResponse,
    BacktestRequest,
    BacktestResponse,
    ConnectionResponse,
    ConnectionState,
    ConnectionValidateRequest,
    Environment,
    HealthResponse,
    KillSwitchRequest,
    LiveEnableRequest,
    OrderIntentRequest,
    OrderIntentResponse,
    RiskConfigInput,
    RiskConfigResponse,
    SessionResponse,
    UnlockRequest,
    WatchlistResponse,
    WatchlistUpdateRequest,
)
from app.security import authenticate_bootstrap_passphrase, issue_session_token, require_session
from app.services.audit import record_audit
from app.services.backtest import BacktestBar, BacktestError, run_event_backtest
from app.services.connection import (
    adapter_for_connection,
    disconnect_connection,
    validate_and_store_connection,
)
from app.services.execution import execute_order_intent

logger = logging.getLogger("alpaca_killer")
WORKER_HEARTBEAT_MAX_AGE = timedelta(minutes=15)


def _fingerprint(config: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _owner(db: Session) -> User:
    owner = db.scalar(select(User).where(User.username == "owner"))
    if owner is None:
        owner = User(username="owner")
        db.add(owner)
        db.flush()
    return owner


def _connection(db: Session, user_id: str, environment: Environment) -> BrokerConnection:
    if environment == Environment.BACKTEST:
        raise HTTPException(status_code=400, detail="Backtest does not have a broker connection")
    connection = db.scalar(
        select(BrokerConnection)
        .where(
            BrokerConnection.user_id == user_id,
            BrokerConnection.environment == environment.value,
            BrokerConnection.disconnected_at.is_(None),
        )
        .order_by(BrokerConnection.verified_at.desc())
    )
    if connection is None:
        raise HTTPException(
            status_code=404, detail="No verified broker connection for this environment"
        )
    return connection


def _connection_summary(connection: BrokerConnection, state: ConnectionState) -> ConnectionResponse:
    return ConnectionResponse(
        broker="alpaca",
        environment=Environment(connection.environment),
        account_id_masked=connection.account_id_masked,
        account_status=connection.account_status,
        trading_blocked=connection.trading_blocked,
        automation_enabled=connection.automation_enabled,
        verified_at=connection.verified_at,
        state=state,
    )


def _ensure_automation(db: Session, user_id: str, environment: Environment) -> AutomationState:
    automation = db.scalar(
        select(AutomationState).where(
            AutomationState.user_id == user_id,
            AutomationState.environment == environment.value,
        )
    )
    if automation is None:
        automation = AutomationState(
            user_id=user_id, environment=environment.value, enabled=False, reduce_only=False
        )
        db.add(automation)
        db.flush()
    return automation


def _kill_state(db: Session, user_id: str) -> KillSwitchState:
    state = db.scalar(select(KillSwitchState).where(KillSwitchState.user_id == user_id))
    if state is None:
        state = KillSwitchState(user_id=user_id, active=False)
        db.add(state)
        db.flush()
    return state


def _paper_worker_status(db: Session) -> tuple[bool, datetime | None]:
    latest = db.scalar(
        select(SystemHealthEvent)
        .where(SystemHealthEvent.component == "paper-worker", SystemHealthEvent.environment == "paper")
        .order_by(SystemHealthEvent.created_at.desc())
        .limit(1)
    )
    if latest is None:
        return False, None
    last_seen = latest.created_at
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    healthy = (
        latest.status == "HEALTHY"
        and datetime.now(UTC) - last_seen <= WORKER_HEARTBEAT_MAX_AGE
    )
    return healthy, last_seen


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime = settings or get_settings()
    engine = create_database_engine(runtime.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Compose deployment executes Alembic before startup. Development/test creates a local schema.
        if not runtime.is_production:
            initialize_database(engine)
        logger.info("service_started", extra={"environment": runtime.app_env})
        yield

    app = FastAPI(
        title=runtime.api_title,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    app.state.settings = runtime
    app.state.db_engine = engine
    app.state.session_factory = create_session_factory(engine)

    origins = runtime.cors_origins or (
        [] if runtime.is_production else ["http://10.0.2.2", "http://localhost"]
    )
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.post("/api/v1/auth/session", response_model=SessionResponse, tags=["authentication"])
    def unlock_session(payload: UnlockRequest, request: Request) -> SessionResponse:
        if not authenticate_bootstrap_passphrase(
            payload.passphrase.get_secret_value(), request.app.state.settings
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid unlock credential"
            )
        token = issue_session_token(request.app.state.settings, "owner")
        return SessionResponse(
            access_token=token,
            expires_in_seconds=request.app.state.settings.session_ttl_minutes * 60,
        )

    @app.post(
        "/api/v1/connections/validate", response_model=ConnectionResponse, tags=["connections"]
    )
    def validate_connection(
        payload: ConnectionValidateRequest,
        user_id: str = Depends(require_session),
        db: Session = Depends(get_db),
        request: Request = None,  # type: ignore[assignment]
    ) -> ConnectionResponse:
        if payload.requested_environment == Environment.BACKTEST:
            raise HTTPException(status_code=400, detail="Backtest mode has no Alpaca credentials")
        try:
            connection = validate_and_store_connection(
                db,
                user_id=user_id,
                api_key=payload.api_key.get_secret_value(),
                api_secret=payload.api_secret.get_secret_value(),
                requested_environment=(
                    payload.requested_environment.value if payload.requested_environment else None
                ),
                fernet=request.app.state.settings.credential_fernet(),
            )
            db.commit()
        except BrokerError as exc:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        state = (
            ConnectionState.CONNECTED_PAPER
            if connection.environment == "paper"
            else ConnectionState.CONNECTED_LIVE
        )
        return _connection_summary(connection, state)

    @app.get("/api/v1/account", response_model=AccountSummary, tags=["account"])
    def get_account(
        request: Request,
        environment: Environment | None = None,
        user_id: str = Depends(require_session),
        db: Session = Depends(get_db),
    ) -> AccountSummary:
        query = select(BrokerConnection).where(
            BrokerConnection.user_id == user_id, BrokerConnection.disconnected_at.is_(None)
        )
        if environment and environment != Environment.BACKTEST:
            query = query.where(BrokerConnection.environment == environment.value)
        connection = db.scalar(query.order_by(BrokerConnection.verified_at.desc()))
        if connection is None:
            raise HTTPException(status_code=404, detail="No verified Alpaca account is connected")
        broker_account: dict[str, Any] = {}
        positions: list[dict[str, Any]] = []
        try:
            adapter = adapter_for_connection(
                connection, request.app.state.settings.credential_fernet()
            )
            broker_account = adapter.get_account()
            positions = adapter.get_positions()
        except Exception:
            # The verified record is still safe to display, but unavailable broker metrics are omitted.
            broker_account = {}
            positions = []
        latest_pnl = db.scalar(
            select(PnLSnapshot)
            .where(PnLSnapshot.environment == connection.environment)
            .order_by(PnLSnapshot.captured_at.desc())
        )
        return AccountSummary(
            broker="alpaca",
            environment=Environment(connection.environment),
            account_id_masked=connection.account_id_masked,
            account_status=connection.account_status,
            trading_blocked=connection.trading_blocked,
            automation_enabled=connection.automation_enabled,
            verified_at=connection.verified_at,
            equity=str(broker_account["equity"])
            if broker_account.get("equity") is not None
            else None,
            buying_power=(
                str(broker_account["buying_power"])
                if broker_account.get("buying_power") is not None
                else None
            ),
            cash=str(broker_account["cash"]) if broker_account.get("cash") is not None else None,
            daily_pnl=str(latest_pnl.daily_pnl) if latest_pnl else None,
            drawdown=str(latest_pnl.drawdown) if latest_pnl else None,
            open_positions=len(positions) if broker_account else None,
            last_updated=utcnow(),
        )

    @app.get("/api/v1/account/environment", response_model=AccountSummary, tags=["account"])
    def get_environment(
        environment: Environment | None = None,
        user_id: str = Depends(require_session),
        db: Session = Depends(get_db),
    ) -> AccountSummary:
        if environment is None:
            connection = db.scalar(
                select(BrokerConnection)
                .where(
                    BrokerConnection.user_id == user_id,
                    BrokerConnection.disconnected_at.is_(None),
                )
                .order_by(BrokerConnection.verified_at.desc())
            )
            if connection is None:
                raise HTTPException(
                    status_code=404, detail="No verified Alpaca account is connected"
                )
        else:
            connection = _connection(db, user_id, environment)
        return AccountSummary(
            broker="alpaca",
            environment=Environment(connection.environment),
            account_id_masked=connection.account_id_masked,
            account_status=connection.account_status,
            trading_blocked=connection.trading_blocked,
            automation_enabled=connection.automation_enabled,
            verified_at=connection.verified_at,
        )

    @app.post("/api/v1/connections/disconnect", tags=["connections"])
    def disconnect(
        environment: Environment,
        user_id: str = Depends(require_session),
        db: Session = Depends(get_db),
    ) -> dict[str, str]:
        connection = _connection(db, user_id, environment)
        disconnect_connection(db, connection, user_id)
        automation = _ensure_automation(db, user_id, environment)
        automation.enabled = False
        connection.disconnected_at = utcnow()
        db.commit()
        return {"status": "disconnected"}

    @app.get("/api/v1/instruments", tags=["market"])
    def get_instruments(
        limit: int = Query(default=200, ge=1, le=1000),
        user_id: str = Depends(require_session),
        db: Session = Depends(get_db),
    ) -> list[dict[str, Any]]:
        rows = db.scalars(
            select(Instrument)
            .where(Instrument.tradable.is_(True))
            .order_by(Instrument.symbol)
            .limit(limit)
        ).all()
        if not rows:
            connection = db.scalar(
                select(BrokerConnection)
                .where(
                    BrokerConnection.user_id == user_id,
                    BrokerConnection.disconnected_at.is_(None),
                )
                .order_by(BrokerConnection.verified_at.desc())
            )
            if connection is not None:
                try:
                    assets = adapter_for_connection(
                        connection, app.state.settings.credential_fernet()
                    ).get_assets()
                    existing = {item.symbol: item for item in db.scalars(select(Instrument)).all()}
                    for asset in assets:
                        symbol = str(asset.get("symbol", "")).upper()
                        if not symbol:
                            continue
                        item = existing.get(symbol)
                        if item is None:
                            item = Instrument(symbol=symbol)
                            db.add(item)
                        item.asset_class = str(asset.get("asset_class", "unknown"))
                        item.tradable = bool(asset.get("tradable", False))
                        item.fractionable = bool(asset.get("fractionable", False))
                        item.shortable = bool(asset.get("shortable", False))
                        item.metadata_json = {"exchange": str(asset.get("exchange", ""))}
                    db.commit()
                    rows = db.scalars(
                        select(Instrument)
                        .where(Instrument.tradable.is_(True))
                        .order_by(Instrument.symbol)
                        .limit(limit)
                    ).all()
                except Exception as exc:
                    raise HTTPException(
                        status_code=503,
                        detail="Instrument universe could not be synchronized from Alpaca",
                    ) from exc
        return [
            {
                "symbol": row.symbol,
                "asset_class": row.asset_class,
                "fractionable": row.fractionable,
                "shortable": row.shortable,
            }
            for row in rows
        ]

    @app.post("/api/v1/instruments/validate", tags=["market"])
    def validate_instrument(
        symbol: str,
        environment: Environment = Environment.PAPER,
        user_id: str = Depends(require_session),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        connection = _connection(db, user_id, environment)
        cached = db.scalar(select(Instrument).where(Instrument.symbol == symbol.upper()))
        if cached is None or not cached.tradable:
            raise HTTPException(
                status_code=404,
                detail="Instrument is not currently eligible in the local synced universe",
            )
        return {
            "symbol": cached.symbol,
            "tradable": cached.tradable,
            "environment": connection.environment,
        }

    @app.get("/api/v1/market/regimes", tags=["analysis"])
    def get_regimes(
        environment: Environment = Environment.PAPER,
        _: str = Depends(require_session),
        db: Session = Depends(get_db),
    ) -> list[dict[str, Any]]:
        rows = db.scalars(
            select(MarketRegime)
            .where(MarketRegime.environment == environment.value)
            .order_by(MarketRegime.created_at.desc())
            .limit(200)
        ).all()
        return [
            {
                "instrument": row.instrument,
                "regime": row.regime,
                "direction": row.direction,
                "confidence": row.confidence,
                "data_timestamp": row.data_timestamp,
                "expires_at": row.expires_at,
                "explanation": row.explanation,
            }
            for row in rows
        ]

    @app.get("/api/v1/signals", tags=["analysis"])
    def get_signals(
        environment: Environment = Environment.PAPER,
        _: str = Depends(require_session),
        db: Session = Depends(get_db),
    ) -> list[dict[str, Any]]:
        rows = db.scalars(
            select(Signal)
            .where(Signal.environment == environment.value)
            .order_by(Signal.generated_at.desc())
            .limit(200)
        ).all()
        return [
            {
                "id": row.id,
                "instrument": row.instrument,
                "strategy": row.strategy_name,
                "side": row.side,
                "status": row.status,
                "expires_at": row.expires_at,
                "explanation": row.explanation,
            }
            for row in rows
        ]

    @app.post("/api/v1/backtests", response_model=BacktestResponse, tags=["backtests"])
    def create_backtest(
        payload: BacktestRequest,
        user_id: str = Depends(require_session),
        db: Session = Depends(get_db),
    ) -> BacktestResponse:
        run = BacktestRun(
            user_id=user_id, status="RUNNING", request_json=payload.model_dump(mode="json")
        )
        db.add(run)
        db.flush()
        try:
            result = run_event_backtest(
                [BacktestBar(**bar.model_dump()) for bar in payload.bars],
                initial_cash=payload.initial_cash,
                commission_per_order=payload.commission_per_order,
                spread_bps=payload.spread_bps,
                slippage_bps=payload.slippage_bps,
                latency_bars=payload.latency_bars,
                fast_window=payload.fast_window,
                slow_window=payload.slow_window,
            )
        except BacktestError as exc:
            run.status = "FAILED"
            run.result_json = {"error": str(exc)}
            db.commit()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        run.status = "COMPLETED"
        run.result_json = result
        record_audit(
            db,
            event_type="BACKTEST_COMPLETED",
            actor=user_id,
            environment="backtest",
            payload={"run_id": run.id, "symbol": payload.symbol},
        )
        db.commit()
        return BacktestResponse(
            id=run.id,
            status=run.status,
            metrics=result["metrics"],
            assumptions=result["assumptions"],
        )

    @app.get("/api/v1/backtests/{run_id}", response_model=BacktestResponse, tags=["backtests"])
    def get_backtest(
        run_id: str, user_id: str = Depends(require_session), db: Session = Depends(get_db)
    ) -> BacktestResponse:
        run = db.scalar(
            select(BacktestRun).where(BacktestRun.id == run_id, BacktestRun.user_id == user_id)
        )
        if run is None or run.status != "COMPLETED":
            raise HTTPException(status_code=404, detail="Completed backtest not found")
        return BacktestResponse(
            id=run.id,
            status=run.status,
            metrics=run.result_json["metrics"],
            assumptions=run.result_json["assumptions"],
        )

    @app.get("/api/v1/positions", tags=["broker-state"])
    def get_positions(
        environment: Environment = Environment.PAPER,
        user_id: str = Depends(require_session),
        db: Session = Depends(get_db),
        request: Request = None,  # type: ignore[assignment]
    ) -> list[dict[str, Any]]:
        connection = _connection(db, user_id, environment)
        try:
            positions = adapter_for_connection(
                connection, request.app.state.settings.credential_fernet()
            ).get_positions()
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail="Broker positions are temporarily unavailable"
            ) from exc
        for position in positions:
            db.add(
                PositionSnapshot(
                    environment=connection.environment,
                    instrument=str(position.get("symbol", "")),
                    quantity=float(position.get("qty", 0) or 0),
                    market_value=float(position.get("market_value", 0) or 0),
                )
            )
        db.commit()
        return positions

    @app.get("/api/v1/orders", tags=["broker-state"])
    def get_orders(
        environment: Environment = Environment.PAPER,
        user_id: str = Depends(require_session),
        db: Session = Depends(get_db),
        request: Request = None,  # type: ignore[assignment]
    ) -> list[dict[str, Any]]:
        connection = _connection(db, user_id, environment)
        try:
            return adapter_for_connection(
                connection, request.app.state.settings.credential_fernet()
            ).get_open_orders()
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail="Broker orders are temporarily unavailable"
            ) from exc

    @app.get("/api/v1/fills", tags=["broker-state"])
    def get_fills(
        environment: Environment = Environment.PAPER,
        _: str = Depends(require_session),
        db: Session = Depends(get_db),
    ) -> list[dict[str, Any]]:
        rows = db.scalars(
            select(Fill)
            .where(Fill.environment == environment.value)
            .order_by(Fill.filled_at.desc())
            .limit(500)
        ).all()
        return [
            {
                "id": row.id,
                "quantity": row.quantity,
                "price": float(row.price),
                "filled_at": row.filled_at,
            }
            for row in rows
        ]

    @app.get("/api/v1/performance", tags=["performance"])
    def get_performance(
        environment: Environment = Environment.PAPER,
        _: str = Depends(require_session),
        db: Session = Depends(get_db),
    ) -> list[dict[str, Any]]:
        rows = db.scalars(
            select(PnLSnapshot)
            .where(PnLSnapshot.environment == environment.value)
            .order_by(PnLSnapshot.captured_at.desc())
            .limit(365)
        ).all()
        return [
            {
                "daily_pnl": float(row.daily_pnl),
                "drawdown": row.drawdown,
                "captured_at": row.captured_at,
            }
            for row in rows
        ]

    @app.get("/api/v1/risk/config", response_model=RiskConfigResponse, tags=["risk"])
    def get_risk_config(
        environment: Environment = Environment.PAPER,
        user_id: str = Depends(require_session),
        db: Session = Depends(get_db),
    ) -> RiskConfigResponse:
        stored = db.scalar(
            select(RiskConfiguration).where(
                RiskConfiguration.user_id == user_id,
                RiskConfiguration.environment == environment.value,
            )
        )
        if stored is None:
            return RiskConfigResponse(
                environment=environment, complete=False, config=None, configuration_fingerprint=None
            )
        return RiskConfigResponse(
            environment=environment,
            complete=stored.complete,
            config=RiskConfigInput(**stored.config_json) if stored.complete else None,
            configuration_fingerprint=_fingerprint(stored.config_json) if stored.complete else None,
        )

    @app.put("/api/v1/risk/config", response_model=RiskConfigResponse, tags=["risk"])
    def put_risk_config(
        payload: RiskConfigInput,
        environment: Environment = Environment.PAPER,
        user_id: str = Depends(require_session),
        db: Session = Depends(get_db),
    ) -> RiskConfigResponse:
        if environment == Environment.BACKTEST:
            raise HTTPException(
                status_code=400, detail="Risk configuration must target paper or live"
            )
        stored = db.scalar(
            select(RiskConfiguration).where(
                RiskConfiguration.user_id == user_id,
                RiskConfiguration.environment == environment.value,
            )
        )
        if stored is None:
            stored = RiskConfiguration(
                user_id=user_id,
                environment=environment.value,
                config_json=payload.model_dump(),
                complete=True,
            )
            db.add(stored)
        else:
            stored.config_json = payload.model_dump()
            stored.complete = True
        record_audit(
            db,
            event_type="RISK_CONFIGURATION_UPDATED",
            actor=user_id,
            environment=environment.value,
            payload={"fingerprint": _fingerprint(payload.model_dump())},
        )
        db.commit()
        return RiskConfigResponse(
            environment=environment,
            complete=True,
            config=payload,
            configuration_fingerprint=_fingerprint(payload.model_dump()),
        )

    @app.get("/api/v1/automation/status", response_model=AutomationResponse, tags=["automation"])
    def automation_status(
        environment: Environment = Environment.PAPER,
        user_id: str = Depends(require_session),
        db: Session = Depends(get_db),
    ) -> AutomationResponse:
        if environment == Environment.BACKTEST:
            return AutomationResponse(
                environment=environment,
                enabled=False,
                reduce_only=False,
                kill_switch_active=bool(_kill_state(db, user_id).active),
                message="Backtest never submits broker orders",
            )
        automation = _ensure_automation(db, user_id, environment)
        kill = _kill_state(db, user_id)
        worker_healthy, worker_last_seen = (
            _paper_worker_status(db) if environment == Environment.PAPER else (None, None)
        )
        db.commit()
        return AutomationResponse(
            environment=environment,
            enabled=automation.enabled,
            reduce_only=automation.reduce_only,
            kill_switch_active=kill.active,
            message="Automation unavailable while kill switch is active"
            if kill.active
            else "Automation status verified",
            worker_healthy=worker_healthy,
            worker_last_seen=worker_last_seen,
        )

    @app.get(
        "/api/v1/automation/watchlist", response_model=WatchlistResponse, tags=["automation"]
    )
    def get_paper_watchlist(
        _: str = Depends(require_session), db: Session = Depends(get_db)
    ) -> WatchlistResponse:
        stored = db.scalar(
            select(StrategyConfig).where(
                StrategyConfig.environment == "paper",
                StrategyConfig.strategy_name == "watchlist",
            )
        )
        symbols = stored.config_json.get("symbols", []) if stored and stored.enabled else []
        return WatchlistResponse(symbols=[str(item).upper() for item in symbols])

    @app.put(
        "/api/v1/automation/watchlist", response_model=WatchlistResponse, tags=["automation"]
    )
    def put_paper_watchlist(
        payload: WatchlistUpdateRequest,
        user_id: str = Depends(require_session),
        db: Session = Depends(get_db),
    ) -> WatchlistResponse:
        stored = db.scalar(
            select(StrategyConfig).where(
                StrategyConfig.environment == "paper",
                StrategyConfig.strategy_name == "watchlist",
            )
        )
        if stored is None:
            stored = StrategyConfig(
                environment="paper",
                strategy_name="watchlist",
                enabled=True,
                config_json={"symbols": payload.symbols},
            )
            db.add(stored)
        else:
            stored.enabled = True
            stored.config_json = {"symbols": payload.symbols}
        record_audit(
            db,
            event_type="PAPER_WATCHLIST_UPDATED",
            actor=user_id,
            environment="paper",
            payload={"symbols": payload.symbols},
        )
        db.commit()
        return WatchlistResponse(symbols=payload.symbols)

    @app.get("/api/v1/automation/worker-status", tags=["automation"])
    def paper_worker_status(
        _: str = Depends(require_session), db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        healthy, last_seen = _paper_worker_status(db)
        return {
            "environment": "paper",
            "healthy": healthy,
            "last_seen": last_seen,
            "message": "Paper worker heartbeat is current" if healthy else "Paper worker is not running or its heartbeat is stale",
            "max_heartbeat_age_seconds": int(WORKER_HEARTBEAT_MAX_AGE.total_seconds()),
        }

    @app.post(
        "/api/v1/automation/enable-paper", response_model=AutomationResponse, tags=["automation"]
    )
    def enable_paper(
        user_id: str = Depends(require_session), db: Session = Depends(get_db)
    ) -> AutomationResponse:
        connection = _connection(db, user_id, Environment.PAPER)
        risk = db.scalar(
            select(RiskConfiguration).where(
                RiskConfiguration.user_id == user_id, RiskConfiguration.environment == "paper"
            )
        )
        kill = _kill_state(db, user_id)
        if kill.active:
            raise HTTPException(status_code=409, detail="Kill switch is active")
        if risk is None or not risk.complete:
            raise HTTPException(
                status_code=409, detail="Configure paper risk limits before enabling automation"
            )
        watchlist = db.scalar(
            select(StrategyConfig).where(
                StrategyConfig.environment == "paper",
                StrategyConfig.strategy_name == "watchlist",
                StrategyConfig.enabled.is_(True),
            )
        )
        if watchlist is None or not watchlist.config_json.get("symbols"):
            raise HTTPException(
                status_code=409, detail="Configure a paper watchlist before enabling automation"
            )
        worker_healthy, worker_last_seen = _paper_worker_status(db)
        if not worker_healthy:
            raise HTTPException(
                status_code=409,
                detail="Paper worker is not running or its heartbeat is stale; no automation was enabled",
            )
        automation = _ensure_automation(db, user_id, Environment.PAPER)
        automation.enabled = True
        automation.enabled_at = utcnow()
        connection.automation_enabled = True
        record_audit(
            db,
            event_type="PAPER_AUTOMATION_ENABLED",
            actor=user_id,
            environment="paper",
            payload={"risk_fingerprint": _fingerprint(risk.config_json)},
        )
        db.commit()
        return AutomationResponse(
            environment=Environment.PAPER,
            enabled=True,
            reduce_only=automation.reduce_only,
            kill_switch_active=False,
            message="Paper automation enabled",
            worker_healthy=worker_healthy,
            worker_last_seen=worker_last_seen,
        )

    @app.post(
        "/api/v1/automation/enable-live", response_model=AutomationResponse, tags=["automation"]
    )
    def enable_live(
        payload: LiveEnableRequest,
        user_id: str = Depends(require_session),
        db: Session = Depends(get_db),
        request: Request = None,  # type: ignore[assignment]
    ) -> AutomationResponse:
        if not request.app.state.settings.allow_live_trading:
            raise HTTPException(
                status_code=503,
                detail="Live automation is disabled by deployment policy; paper mode only",
            )
        connection = _connection(db, user_id, Environment.LIVE)
        risk = db.scalar(
            select(RiskConfiguration).where(
                RiskConfiguration.user_id == user_id, RiskConfiguration.environment == "live"
            )
        )
        kill = _kill_state(db, user_id)
        if kill.active:
            raise HTTPException(status_code=409, detail="Kill switch is active")
        if risk is None or not risk.complete:
            raise HTTPException(
                status_code=409, detail="Live automation requires complete risk limits"
            )
        if payload.configuration_fingerprint != _fingerprint(risk.config_json):
            raise HTTPException(
                status_code=409,
                detail="Risk configuration changed; review the exact current limits and confirm again",
            )
        if connection.environment != "live":
            raise HTTPException(
                status_code=409, detail="Server-verified live connection is required"
            )
        automation = _ensure_automation(db, user_id, Environment.LIVE)
        automation.enabled = True
        automation.enabled_at = utcnow()
        connection.automation_enabled = True
        record_audit(
            db,
            event_type="LIVE_AUTOMATION_ENABLED",
            actor=user_id,
            environment="live",
            payload={
                "risk_fingerprint": _fingerprint(risk.config_json),
                "explicit_confirmation": True,
            },
        )
        db.commit()
        return AutomationResponse(
            environment=Environment.LIVE,
            enabled=True,
            reduce_only=automation.reduce_only,
            kill_switch_active=False,
            message="Live automation explicitly enabled with current risk limits",
        )

    @app.post("/api/v1/automation/disable", response_model=AutomationResponse, tags=["automation"])
    def disable_automation(
        environment: Environment = Environment.PAPER,
        user_id: str = Depends(require_session),
        db: Session = Depends(get_db),
    ) -> AutomationResponse:
        if environment == Environment.BACKTEST:
            raise HTTPException(status_code=400, detail="Backtest has no broker automation")
        connection = _connection(db, user_id, environment)
        automation = _ensure_automation(db, user_id, environment)
        automation.enabled = False
        connection.automation_enabled = False
        record_audit(
            db,
            event_type="AUTOMATION_DISABLED",
            actor=user_id,
            environment=environment.value,
            payload={},
        )
        db.commit()
        return AutomationResponse(
            environment=environment,
            enabled=False,
            reduce_only=automation.reduce_only,
            kill_switch_active=_kill_state(db, user_id).active,
            message="Automation disabled",
        )

    @app.post("/api/v1/kill-switch/activate", response_model=AutomationResponse, tags=["safety"])
    def activate_kill_switch(
        payload: KillSwitchRequest,
        user_id: str = Depends(require_session),
        db: Session = Depends(get_db),
    ) -> AutomationResponse:
        kill = _kill_state(db, user_id)
        kill.active = True
        kill.activated_at = utcnow()
        kill.reason = payload.reason
        for state in db.scalars(
            select(AutomationState).where(AutomationState.user_id == user_id)
        ).all():
            state.enabled = False
        for connection in db.scalars(
            select(BrokerConnection).where(BrokerConnection.user_id == user_id)
        ).all():
            connection.automation_enabled = False
        record_audit(
            db,
            event_type="KILL_SWITCH_ACTIVATED",
            actor=user_id,
            payload={"reason": payload.reason},
        )
        db.commit()
        return AutomationResponse(
            environment=Environment.PAPER,
            enabled=False,
            reduce_only=False,
            kill_switch_active=True,
            message="Kill switch active; no new automated broker orders may be submitted",
        )

    @app.post("/api/v1/kill-switch/deactivate", response_model=AutomationResponse, tags=["safety"])
    def deactivate_kill_switch(
        user_id: str = Depends(require_session), db: Session = Depends(get_db)
    ) -> AutomationResponse:
        kill = _kill_state(db, user_id)
        kill.active = False
        kill.reason = None
        # Deliberately does not re-enable automation; paper/live require separate explicit activation.
        record_audit(db, event_type="KILL_SWITCH_DEACTIVATED", actor=user_id, payload={})
        db.commit()
        return AutomationResponse(
            environment=Environment.PAPER,
            enabled=False,
            reduce_only=False,
            kill_switch_active=False,
            message="Kill switch cleared; automation remains disabled",
        )

    @app.post("/api/v1/orders/intents", response_model=OrderIntentResponse, tags=["execution"])
    def create_order_intent(
        payload: OrderIntentRequest,
        user_id: str = Depends(require_session),
        db: Session = Depends(get_db),
        request: Request = None,  # type: ignore[assignment]
    ) -> OrderIntentResponse:
        try:
            intent = execute_order_intent(
                db,
                user_id=user_id,
                request=payload,
                fernet=request.app.state.settings.credential_fernet(),
                allow_live_trading=request.app.state.settings.allow_live_trading,
            )
            db.commit()
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        message = (
            "Order submitted or reconciled through Alpaca"
            if intent.status not in {"RISK_REJECTED", "PAUSED", "SUBMISSION_UNCERTAIN"}
            else "No new broker order was sent"
        )
        return OrderIntentResponse(
            intent_id=intent.id,
            status=intent.status,
            client_order_id=intent.client_order_id,
            message=message,
        )

    @app.get("/api/v1/audit-log", tags=["audit"])
    def get_audit_log(
        environment: Environment | None = None,
        _: str = Depends(require_session),
        db: Session = Depends(get_db),
    ) -> list[dict[str, Any]]:
        query = select(AuditEvent)
        if environment:
            query = query.where(AuditEvent.environment == environment.value)
        rows = db.scalars(query.order_by(AuditEvent.created_at.desc()).limit(500)).all()
        return [
            {
                "id": row.id,
                "event_type": row.event_type,
                "environment": row.environment,
                "correlation_id": row.correlation_id,
                "payload": row.payload_json,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    @app.get("/api/v1/health", response_model=HealthResponse, tags=["operations"])
    def health(db: Session = Depends(get_db)) -> HealthResponse:
        try:
            db.execute(text("SELECT 1"))
            database = "ok"
        except Exception:
            database = "unavailable"
        return HealthResponse(
            status="ok" if database == "ok" else "degraded",
            database=database,
            timestamp=datetime.now(UTC),
            automation_available=database == "ok",
        )

    @app.websocket("/api/v1/stream")
    async def stream(websocket: WebSocket) -> None:
        # WebSocket is authenticated with the same short-lived session token in query `access_token`.
        await websocket.accept()
        token = websocket.query_params.get("access_token")
        if not token:
            await websocket.close(code=4401)
            return
        import jwt

        try:
            jwt.decode(token, websocket.app.state.settings.jwt_secret, algorithms=["HS256"])
        except jwt.PyJWTError:
            await websocket.close(code=4401)
            return
        try:
            await websocket.send_json(
                {
                    "type": "health",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "message": "Authenticated stream established",
                }
            )
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            return

    return app


app = create_app()
