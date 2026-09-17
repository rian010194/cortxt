"""Work-record operations over the append-only Core store (ADR-050).

A thin surface, deliberately: every mutation is a single
``CoreStore.append`` whose deterministic outcome envelope (``appended`` /
``re-delivery`` / ``conflict``) is returned verbatim. This module adds no
digest logic, no storage rules and no validation of its own beyond the
record schema in ``record.py``. It mirrors the shape of
``widget_contract/product_packaging/ops_api.py`` and imports nothing from
it. The store itself is finished and is not modified.

The three ADR-050 rules land here as follows:

1. **Before a repository, before an issue.** ``create`` takes a record and
   nothing else; ``issue_ref`` defaults to ``None`` and creation never
   requires it. There is no repository parameter anywhere in this module.
2. **Revision is supersession, never mutation.** ``revise`` appends a NEW
   record naming the earlier one; nothing is ever edited or deleted, and the
   store offers no API for either. ``history`` is the method this rule
   exists for: the operator must be able to see that they changed their
   mind, and what they changed it from.
3. **A record may be a finished result.** ``state`` is content, so no method
   here closes, completes or transitions anything.

Identity is the payload digest -- pure content addressing. Two identical
records are one record; the second append renders ``re-delivery`` and
appends nothing. A different payload under the same identity renders an
explicit ``conflict`` that is never merged or overwritten. Neither stance is
re-implemented here; both are the store's, surfaced unchanged.

``head`` refuses a fork. Append order is not a chain, and two independent
revisions of the same work are a real possibility, so the head is derived
from the supersession relation. When more than one record in a work is
unsuperseded, this module raises rather than picking one: a fork is a fact
the operator must see, not something an API resolves on their behalf. That
is the same conflict-not-merge stance the store takes.

The store's internal ``record_hash`` is never exposed to callers, following
``_envelope_view``'s example in the packaging ops API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from state.core_store import CoreError, CoreStore

from .record import RECORD_KIND, WorkRecordError, validate_work_record


def _wrap_core(error: CoreError) -> WorkRecordError:
    """Surface a store refusal unchanged, under the store's own category."""
    return WorkRecordError(error.message, kind=error.category)


def _envelope_view(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """The store envelope fields a caller may see (never the internal hash)."""
    return {
        "identity": envelope["identity"],
        "record_digest": envelope["record_digest"],
        "appended_at": envelope["appended_at"],
        "issue_ref": envelope["issue_ref"],
        "supersedes": envelope["supersedes"],
        "record": envelope["payload"],
    }


def _sort_key(view: Mapping[str, Any]) -> tuple[str, str]:
    return (view["appended_at"], view["identity"])


class WorkRecordOpsApi:
    """Create, revise and read work records over the Core store."""

    def __init__(self, store: CoreStore | str | Path) -> None:
        # A caller may hand over either a ready CoreStore or the durable
        # store ROOT (str/Path) to build one against, exactly as
        # PackagingOpsApi does.
        if isinstance(store, (str, Path)):
            try:
                store = CoreStore(store)
            except CoreError as exc:
                raise _wrap_core(exc) from exc
        if not isinstance(store, CoreStore):
            raise WorkRecordError("store must be a CoreStore or a store root path")
        self._store = store

    @property
    def store(self) -> CoreStore:
        return self._store

    # --- write paths ------------------------------------------------------

    def create(self, record: Mapping[str, Any], *,
               issue_ref: str | None = None) -> dict[str, Any]:
        """Append a new work record; identity is the payload digest.

        ``issue_ref`` is optional and opaque (ADR-050 rule 1): a work record
        is created before any repository is chosen and before any GitHub
        issue exists.
        """
        return self._append(record, issue_ref=issue_ref, supersedes=None)

    def revise(self, record: Mapping[str, Any], *, supersedes: str,
               issue_ref: str | None = None) -> dict[str, Any]:
        """Append a revision superseding ``supersedes`` (ADR-050 rule 2).

        The earlier record stays stored, readable and byte-identical. The
        store already refuses a ``supersedes`` naming no stored record; that
        check is not re-implemented or softened here, only surfaced.
        """
        if not isinstance(supersedes, str) or not supersedes:
            raise WorkRecordError("supersedes is required")
        return self._append(record, issue_ref=issue_ref, supersedes=supersedes)

    def _append(self, record: Mapping[str, Any], *, issue_ref: str | None,
                supersedes: str | None) -> dict[str, Any]:
        validate_work_record(record)
        try:
            # identity is left to the store: it defaults to the payload
            # digest, which is what makes a genuine retry a re-delivery.
            return self._store.append(dict(record), issue_ref=issue_ref,
                                      supersedes=supersedes)
        except CoreError as exc:
            raise _wrap_core(exc) from exc

    # --- read paths (pure reads) -----------------------------------------

    def get(self, identity: str) -> dict[str, Any] | None:
        try:
            envelope = self._store.get(identity)
        except CoreError as exc:
            raise _wrap_core(exc) from exc
        if envelope is None:
            return None
        if envelope["payload"].get("record_kind") != RECORD_KIND:
            return None
        return _envelope_view(envelope)

    def list_records(self, work_id: str | None = None) -> list[dict[str, Any]]:
        """Every work record, optionally one work's, in deterministic order.

        The store holds several domains in one log and offers no
        query-by-field, so listing means iterating and filtering on
        ``record_kind``.
        """
        try:
            envelopes = self._store.iter_records()
        except CoreError as exc:
            raise _wrap_core(exc) from exc
        views: list[dict[str, Any]] = []
        for envelope in envelopes:
            payload = envelope["payload"]
            if not isinstance(payload, dict):
                continue
            if payload.get("record_kind") != RECORD_KIND:
                continue
            if work_id is not None and payload.get("work_id") != work_id:
                continue
            views.append(_envelope_view(envelope))
        views.sort(key=_sort_key)
        return views

    def head(self, work_id: str) -> dict[str, Any] | None:
        """The one record in this work that nothing supersedes.

        Derived from the supersession relation, not from append order. A
        forked work -- two unsuperseded records -- raises, naming both
        digests: the operator resolves a fork, this API does not.
        """
        views = self.list_records(work_id)
        if not views:
            return None
        superseded = {view["supersedes"] for view in views
                      if view["supersedes"] is not None}
        heads = [view for view in views if view["record_digest"] not in superseded]
        if len(heads) > 1:
            digests = ", ".join(view["record_digest"] for view in heads)
            raise WorkRecordError(
                f"work {work_id!r} has a forked supersession chain; "
                f"unsuperseded records: {digests}",
                kind="forked_chain")
        return heads[0] if heads else None

    def history(self, work_id: str) -> list[dict[str, Any]]:
        """The work's chain, oldest first, with the supersession relation.

        Each entry carries its own ``record_digest`` and the
        ``supersedes`` digest it replaced, so a reader can see that the
        operator changed their mind and what they changed it from (rule 2).
        Ordering follows the relation: a record is emitted only after the
        record it supersedes. Records whose ``supersedes`` names nothing in
        this work start the chain; anything left unreachable is emitted last
        in deterministic order rather than hidden.
        """
        views = self.list_records(work_id)
        known = {view["record_digest"] for view in views}
        emitted: set[str] = set()
        chain: list[dict[str, Any]] = []
        pending = list(views)
        while pending:
            ready = [view for view in pending
                     if view["supersedes"] is None
                     or view["supersedes"] not in known
                     or view["supersedes"] in emitted]
            if not ready:
                break
            for view in ready:
                chain.append(view)
                emitted.add(view["record_digest"])
            pending = [view for view in pending
                       if view["record_digest"] not in emitted]
        chain.extend(pending)
        return chain


__all__ = ["WorkRecordOpsApi"]
