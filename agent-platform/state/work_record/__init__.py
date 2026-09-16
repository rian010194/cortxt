"""Work-record domain (ADR-050): the durable artefact a dialogue produces.

Domain and operations only -- no HTTP route, no renderer, no host wiring.
``record`` holds the closed payload model; ``ops_api`` is the thin surface
over the append-only Core store. See ``record`` for the three ADR-050 rules
that govern both.
"""

from __future__ import annotations

from .record import (
    RECORD_KIND,
    STATE_OPEN,
    STATE_SETTLED,
    WorkRecordError,
    build_work_record,
    validate_work_record,
)

__all__ = [
    "RECORD_KIND",
    "STATE_OPEN",
    "STATE_SETTLED",
    "WorkRecordError",
    "build_work_record",
    "validate_work_record",
]
