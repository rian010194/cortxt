"""The single durable home for "is this mandate approved, and by what?" (S7d, #473).

Before this module three readers resolved operator approval differently and
disagreed about the same Issue (#472 dogfood finding 3): the dispatch request
read ``## Approval status`` plus a later explicit operator retry-authorization
comment and reported the issue eligible, while the Workstream projection read
only ``## Approval`` / ``## Human approval`` / ``## Operator approval``, ignored
negations, and reported ``approval_recorded: false`` for the very same issue.
Operator approval is the boundary the whole execution model rests on, so it
must have exactly one resolution and one provenance label.

Resolution rules (unchanged from the dispatch request's own, now shared):

- Only *positive* approval counts. An explicit negation in the section
  (``... is not approved``, ``pending``) means no approval -- an issue that
  records "implementation is not approved yet" is not approved.
- A later explicit operator **retry authorization** comment supersedes the
  issue body, resolved time-ordered by ``createdAt`` (ties broken by comment
  id), never by list position. Only comments carrying an explicit retry marker
  qualify; routine automation status comments never do, and bot authors are
  never eligible.
- Comments are optional. A caller that reads issues without them (the
  Workstream list projection uses ``gh issue list``, which carries no
  comments) resolves from the body alone and says so through ``source`` --
  it never silently claims the comment-aware answer.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

APPROVAL_SECTIONS = ("Approval status", "Approval", "Human approval", "Operator approval")

SOURCE_BODY = "issue-body-approval-status"
SOURCE_RETRY_COMMENT = "issue-comment-retry-authorization"

# Positive approval only: any explicit negation means the issue is not approved
# for dispatch (issue #471 records "Implementation start is not approved").
NEGATED_APPROVAL = re.compile(
    r"\bnot\s+(?:yet\s+)?(?:approved|authorized|permitted|allowed|sanctioned|granted)\b"
    r"|\bpending\b",
    re.I)

# A retry/authorization comment is only ever treated as the operator's current
# authorization when it carries one of these explicit markers -- an ordinary
# status update (dispatch notice, claim record, run result) never qualifies,
# so routine automation comments can never be mistaken for a fresh approval.
RETRY_AUTH_MARKERS = re.compile(
    r"\bretry\s+approved\b|\boperator\s+retry\s+decision\b|\bretry\s+authoriz(?:ed|ation)\b",
    re.I)

# Comment authors whose comments are never eligible authorizations, regardless
# of wording -- automation posts status, never operator authorization.
NON_OPERATOR_AUTHORS = {"github-actions", "github-actions[bot]"}


def latest_retry_authorization(comments: Sequence[Any] | None) -> str | None:
    """The most recent explicit operator retry authorization comment, or None.

    Resolution is deterministic and time-ordered by the comment's own
    ``createdAt`` (ties broken by comment id) -- never by list position, and
    never a fixed/first match -- so a later retry authorization always
    supersedes an earlier one, and a stale one is never picked merely because
    it appears first. Bot comments and non-matching status comments are not
    candidates; a negated candidate ("retry ... not approved") is dropped.
    """
    if not comments:
        return None
    candidates: list[tuple[str, str, str]] = []
    for comment in comments:
        if not isinstance(comment, Mapping):
            continue
        author = comment.get("author")
        login = (author.get("login") if isinstance(author, Mapping) else author) or ""
        if str(login) in NON_OPERATOR_AUTHORS:
            continue
        body = str(comment.get("body") or "")
        if not RETRY_AUTH_MARKERS.search(body) or NEGATED_APPROVAL.search(body):
            continue
        created_at = str(comment.get("createdAt") or "")
        if not created_at:
            continue
        candidates.append((created_at, str(comment.get("id") or ""), body))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[-1][2]


def _approval_section(body: str) -> str | None:
    from .detail import _section

    return _section(body or "", APPROVAL_SECTIONS)


def resolve_approval(body: str, comments: Sequence[Any] | None = None) -> dict[str, Any]:
    """Resolve one Issue's operator approval, with explicit provenance.

    Returns ``{"reference", "source", "recorded"}``. ``reference`` is the
    approval text that binds (the retry-authorization comment when one
    supersedes the body, otherwise the body's approval section); ``source`` is
    the provenance label, or None when nothing positive was recorded;
    ``recorded`` is the boolean a summary view renders.
    """
    retry = latest_retry_authorization(comments)
    if retry is not None:
        return {"reference": retry, "source": SOURCE_RETRY_COMMENT, "recorded": True}
    value = _approval_section(body)
    if value is None or NEGATED_APPROVAL.search(value):
        return {"reference": None, "source": None, "recorded": False}
    return {"reference": value, "source": SOURCE_BODY, "recorded": True}


def approval_reference(body: str, comments: Sequence[Any] | None = None) -> str | None:
    """The binding approval reference alone, or None when not approved."""
    return resolve_approval(body, comments)["reference"]
