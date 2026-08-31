"""Thin port around the one sanctioned review path (S7c, #472).

Cortxt OS must never mark work successful or edit arbitrary ``workflow:*``
labels. Two boundaries already own the review loop and this module only
re-exposes them, unchanged, so the OS never grows a second path:

- **Submission** is ``cortxt_mcp.run_lifecycle.RunLifecycleService.submit_for_review``
  (Tier-1 MCP tool ``cortxt_run_submit_for_review``): idempotent by
  caller-supplied ``idempotency_key`` + canonical payload hash, accepts only a
  complete result envelope whose ``issue_id``/``run_id`` match durable state,
  and records a local ``run.review_submitted`` event -- no ``gh`` call, no
  label change (AC7).
- **GitHub state movement** ``in-progress -> review`` is
  ``daemon.review_sync.sync_review_submissions``, which is idempotent by its
  own persisted markers (AC8).

``sync_run_review_submissions`` **is** the object ``daemon.review_sync``
exposes; ``is`` identity is asserted in the S7c tests so a future divergent
copy fails loudly. ``submit_run_for_review`` is a thin wrapper that delegates
verbatim to the lifecycle service's own method -- it adds no authorization
surface and no payload shaping, but it is not the same object, so no identity
assertion covers it.
"""
from __future__ import annotations

from daemon.review_sync import report_counts, sync_review_submissions as sync_run_review_submissions

__all__ = ["submit_run_for_review", "sync_run_review_submissions", "report_counts"]


def submit_run_for_review(lifecycle, arguments, binding):
    """Delegate verbatim to the canonical lifecycle submission function.

    ``lifecycle`` is a ``cortxt_mcp.run_lifecycle.RunLifecycleService``. This
    wrapper adds no authorization surface and no payload shaping: the mandate
    ``binding`` and strict envelope validation are the lifecycle service's own.
    """
    return lifecycle.submit_for_review(arguments, binding)
