"""BudgetGate — fail-closed, system-managed spend guard for real inference calls.

Reads an absolute spend ceiling from env ``FAS2A_INFERENCE_BUDGET_MAX`` (system-managed,
never a number embedded in code or the operator prompt). Default when absent = 0
(fail-closed: no real call may proceed). Each permitted call appends a spend row to a
SQLite table ``fas2a_inference_spend`` for later analysis.
"""

from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

DEFAULT_DB = Path.home() / "AppData/Local/hermes/profiles/coordinator/state.db"


class BudgetExhausted(RuntimeError):
    """Raised when the real-inference budget is exhausted (blocks before HTTP)."""


class BudgetGate:
    """Gate real-inference calls behind a system-managed ceiling.

    ``invoke`` is the callable that performs the real model call; the gate checks the
    ceiling before any network, blocks when exhausted, and records spend on success.
    Because ``InferencePort.invoke`` returns an ``int`` (not an envelope), metadata is
    passed explicitly via ``record``/``task_id`` injection by the caller where available.
    """

    def __init__(self, max_calls: int | None = None, db_path: Path | str | None = None) -> None:
        if max_calls is not None:
            self._max_calls = max_calls
        else:
            raw = os.environ.get("FAS2A_INFERENCE_BUDGET_MAX")
            self._max_calls = int(raw) if raw is not None and raw.isdigit() else 0
        self._db = Path(db_path) if db_path else DEFAULT_DB
        self._last_task_id: str | None = None
        self._route_id: str = "l0-default"
        self._ensure_table()

    def _ensure_table(self) -> None:
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fas2a_inference_spend (
                    timestamp REAL,
                    task_id TEXT,
                    cost_status TEXT,
                    latency_ms INTEGER,
                    route_id TEXT,
                    selected_route_id TEXT
                )
                """
            )

    @property
    def remaining(self) -> int:
        """Remaining attempts = ceiling - DB-spend-count (fail-closed on unreadable DB)."""
        return max(0, self._max_calls - self._count_spend())

    def _count_spend(self) -> int:
        """Count TRUE call-units (attempt_started rows), not all rows.

        A single call logs 1 attempt_started row (+ an outcome row success/failed).
        Counting only attempt_started ensures one call = one budget unit (CP3.1 P1),
        so a failed call cannot consume budget twice.
        """
        try:
            with sqlite3.connect(self._db) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM fas2a_inference_spend WHERE cost_status='attempt_started'"
                ).fetchone()
            return int(row[0]) if row else 0
        except Exception:  # fail-closed: cannot read spend -> refuse further calls
            return self._max_calls

    def set_task_id(self, task_id: str) -> None:
        """Attach the current task id for the next spend row."""
        self._last_task_id = task_id

    def set_route_id(self, route_id: str) -> None:
        """Attach the route for the next spend rows (Fas7 Beslut 6 route isolation).

        Default stays ``l0-default`` so behaviour is unchanged until a caller
        (e.g. ``TextInferencePort``) names its route.
        """
        self._route_id = route_id

    def record(
        self,
        cost_status: str = "unknown",
        latency_ms: int = 0,
        route_id: str = "l0-default",
        selected_route_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                "INSERT INTO fas2a_inference_spend "
                "(timestamp, task_id, cost_status, latency_ms, route_id, selected_route_id) "
                "VALUES (?,?,?,?,?,?)",
                (
                    time.time(),
                    task_id or self._last_task_id or "",
                    cost_status,
                    int(latency_ms or 0),
                    route_id,
                    selected_route_id,
                ),
            )

    def __call__(self, invoke: Callable[..., object], *args, **kwargs):
        if self.remaining < 1:
            raise BudgetExhausted(
                f"real-inference budget exhausted (<=0 of {self._max_calls} calls remain); blocking before HTTP"
            )
        # Record an attempt row UP FRONT so the ceiling advances even if the call fails (CP1.1 P2):
        # a raised/failed attempt still consumes budget, preventing silent bypass via retries.
        self.record(cost_status="attempt_started", latency_ms=0,
                     route_id=self._route_id, selected_route_id=self._route_id)
        started = time.monotonic()
        try:
            result = invoke(*args, **kwargs)
        except BaseException:  # record the failed outcome + latency, then re-raise (CP2.1 P2)
            self.record(
                cost_status="failed",
                latency_ms=int((time.monotonic() - started) * 1000),
                route_id=self._route_id,
                selected_route_id=self._route_id,
            )
            raise
        # Success outcome row with latency, so a completed call is distinguishable from an
        # abandoned attempt (CP3.1 P2).
        self.record(
            cost_status="success",
            latency_ms=int((time.monotonic() - started) * 1000),
            route_id=self._route_id,
            selected_route_id=self._route_id,
        )
        return result
