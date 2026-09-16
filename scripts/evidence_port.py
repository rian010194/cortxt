#!/usr/bin/env python3
"""Read-only evidence port: verify a non-mutating Run's structured report (W-4, #614).

A mutating Run's claimed success is gated on a correlated, landed commit
(`commit_evidence.verify_commit_correlation`, #490). A read-only Run — research,
observation — has no commit by design, so #614 gives it its own fail-closed
settlement gate: the run's structured completion-report channel IS its
evidence. The worker embeds its observation (the packaged-workstream
projection it read through the W-3 ops API) in the report payload; this port
re-verifies, settlement-side, that the envelope still carries a completed,
current-version report whose observation matches the canonical frozen-oracle
digest computed from the report's own `observed` object.

Mirrors the Evidence Gate's shape deliberately:

- pure with respect to the platform: reads the result envelope and the Run
  record, returns `ReadonlyReportEvidence` or a `CorrelationFailure` carrying
  a stable code (reusing `commit_evidence.CorrelationFailure`, so the failure
  vocabulary and the dispatcher's blocked-envelope projection stay one shape);
- never decides what to do with either — `Dispatcher.complete()` owns that
  (W-4 glue: a non-mutating `succeeded` runs this gate; any failure converts
  to `blocked`, never `succeeded`);
- correlation first: run_id/issue_id/request_id must be present and equal the
  durable Run record, exactly as the mutating gate requires (#490), because a
  report for a different Run is nobody's evidence;
- every check fails closed: a missing, unverifiable or tampered report is a
  structured refusal, never a pass.

Tamper model: the platform's report reader
(`routing.completion_report.read_completion_report`) verified the file at
classification time — mtime-correlated to this invocation, decoded, version-
checked. Between that read and settlement the report's *content* travels
inside the result envelope, so this port re-checks the carried payload
(version, strict `completed`) and recomputes the digest of the carried
`observed` object against the envelope's recorded `observed_digest`. An
observation altered (or a digest swapped) after the write cannot pass both
sides of that equality.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Callable, Optional

from commit_evidence import CorrelationFailure

#: The report contract version this port verifies. Matches
#: `routing.completion_report.REPORT_VERSION`; re-declared here (with a
#: cross-check in the tests) so the scripts/ layer stays import-light and the
#: two constants cannot drift silently.
READONLY_REPORT_VERSION = 1

#: The envelope key that carries the packaged workstream observation, and the
#: envelope key that carries its canonical digest. Owned here so a writer
#: cannot scatter variant names the gate would miss.
OBSERVED_KEY = "observed"
OBSERVED_DIGEST_KEY = "observed_digest"

#: Envelope gate markers, mirroring the mutating gate's
#: `evidence_gate: commit_correlated` / `commit_correlation_failed` pairs.
EVIDENCE_GATE_READONLY = "readonly_report_correlated"
READONLY_GATE_FAILED = "readonly_report_failed"

#: The stable failure code for any unverifiable read-only report. One code,
#: like the mutating gate's refusal family, so a reviewer reads "the evidence
#: could not be verified", not a taxonomy of ways to skip verification.
READONLY_FAILURE = "readonly_report_unverifiable"


@dataclass(frozen=True)
class ReadonlyReportEvidence:
    """Durable, correlated proof that a read-only Run's report verified."""

    run_id: str
    issue_id: str
    report_version: int
    observed_digest: str
    verified_at: float
    request_id: Optional[str] = None

    def as_record(self) -> dict:
        """The shape written onto the durable Run record and its envelope."""
        return {
            "run_id": self.run_id,
            "issue_id": self.issue_id,
            "request_id": self.request_id,
            "report_version": self.report_version,
            "observed_digest": self.observed_digest,
            "verified_at": self.verified_at,
        }


def observed_digest(observation) -> "str | None":
    """The frozen-oracle digest of `observation`, or None when uncomputable.

    Canonicalization is EXACTLY the packaging layer's frozen-oracle form
    (`widget_contract.product_packaging._digest.canonical_object`):
    `json.dumps(obj, sort_keys=True, separators=(",", ":"),
    ensure_ascii=True, default=str)`, encoded UTF-8, with no trailing
    newline. A digest binds evidence only if both sides of the equality use
    the same canonical form, so the W-4 port borrows the packaging rules
    verbatim instead of inventing a second one (the cross-layer drift the
    W-2b review flagged as a wrong-form, self-consistent-but-incompatible
    digest). Returns None for a missing observation or one that cannot be
    serialized — a fail-closed caller turns that into a refusal, never a pass.
    """
    if observation is None:
        return None
    try:
        canonical = json.dumps(observation, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=True, default=str)
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_readonly_report(
    run,
    result_envelope: dict,
    *,
    repo_path=None,
    clock: Callable[[], float] = time.time,
):
    """Verify that `run`'s claimed success is backed by a verified report (#614).

    The conditions, in order: the envelope correlates to the Run record
    (run_id/issue_id/request_id present and equal); the envelope still names
    a `completed` structured report; the carried payload satisfies the
    report contract (implemented `report_version`, strict boolean
    `completed`, not `failed`); the payload embeds a non-empty `observed`
    object; and that object's canonical digest equals the envelope's
    `observed_digest`.

    Returns ``ReadonlyReportEvidence`` on success, ``CorrelationFailure``
    otherwise. `repo_path` is accepted for signature parity with
    `verify_commit_correlation` and is unused: a read-only Run's evidence is
    the report, never a commit in a repository.
    """
    envelope = result_envelope or {}

    # Correlation is mandatory, not opportunistic — same order and same rule
    # as the mutating gate: all three identity fields must be present and
    # match the approved Run record exactly, so a worker cannot choose
    # whether to be checked by omitting them (the adapter path overwrites
    # them from the Run record via `enrich_run_correlation`; a caller that
    # bypasses that path is refused here instead of trusted).
    for field, expected, code in (
        ("run_id", getattr(run, "run_id", None), "run_correlation_mismatch"),
        ("issue_id", getattr(run, "issue_id", None), "issue_correlation_mismatch"),
        ("request_id", getattr(run, "request_id", None), "request_correlation_mismatch"),
    ):
        if expected is None:
            return CorrelationFailure(
                f"{field}_not_recorded",
                f"the Run record carries no {field}, so nothing can be correlated against it",
                "A read-only Run must record its approved identity before dispatch; "
                "re-launch it through the sanctioned path.")
        claimed = envelope.get(field)
        if claimed is None:
            return CorrelationFailure(
                code,
                f"result envelope omits {field}; correlation cannot be established",
                "A read-only Run's result must state its identity. An omitted field "
                "is not a passed check.")
        if claimed != expected:
            return CorrelationFailure(
                code,
                f"result envelope reports {field} {claimed!r}, Run record is {expected!r}",
                "The worker returned a result for a different Run, Issue or approved "
                "request; discard it and re-run this Run.")

    # The whole structured channel, re-checked settlement-side. The adapter
    # consulted the platform reader at classification time; this port does
    # not trust that verdict second-hand, because the envelope content can
    # change between the two reads.
    report_state = envelope.get("report_state")
    if report_state != "completed":
        return CorrelationFailure(
            READONLY_FAILURE,
            f"the Run's structured completion report is {report_state!r}, not "
            f"'completed'; a read-only Run's report IS its evidence",
            "Re-run the read-only task so it writes a complete, correlated "
            "completion report; a missing, unreadable, invalid or incomplete "
            "report can never settle this Run as succeeded.")

    payload = envelope.get("report_payload")
    if not isinstance(payload, dict):
        return CorrelationFailure(
            READONLY_FAILURE,
            "the completed report's payload was not carried onto the envelope, so "
            "the evidence cannot be re-verified settlement-side",
            "The adapter must carry the decoded report payload in the envelope's "
            "'report_payload' field for the settlement-side verification.")

    version = payload.get("report_version", READONLY_REPORT_VERSION)
    if version != READONLY_REPORT_VERSION:
        return CorrelationFailure(
            READONLY_FAILURE,
            f"the completion report names version {version!r}, which this reader "
            "does not implement",
            "A report contract change stops the line rather than being guessed at; "
            "re-run with a runtime that writes the implemented report version.")

    completed = payload.get("completed")
    if not isinstance(completed, bool) or completed is not True:
        # The truthiness defect stays closed here too: `"false"`, 1 or a
        # missing key is not a verdict.
        return CorrelationFailure(
            READONLY_FAILURE,
            f"the completion report's `completed` is {completed!r}, not a strict True",
            "A report that does not state completion in the implemented contract "
            "is not evidence of completion.")
    if payload.get("failed") is True:
        return CorrelationFailure(
            READONLY_FAILURE,
            "the completion report states the task failed",
            "A failed task is not a completed observation; re-run the task.")

    observation = payload.get(OBSERVED_KEY)
    if not isinstance(observation, dict) or not observation:
        return CorrelationFailure(
            READONLY_FAILURE,
            f"the completion report carries no non-empty '{OBSERVED_KEY}' object: "
            "a read-only Run must embed the observation it actually made",
            "Re-run the read-only task so its observation is embedded in the "
            "completion report; an absent or empty observation proves nothing "
            "was read.")

    digest = observed_digest(observation)
    if digest is None:
        return CorrelationFailure(
            READONLY_FAILURE,
            "the observation could not be canonicalized under the frozen-oracle "
            "form, so its digest cannot be verified",
            "The observation must be a JSON-serializable object; re-run the task.")
    if envelope.get(OBSERVED_DIGEST_KEY) != digest:
        return CorrelationFailure(
            READONLY_FAILURE,
            f"the '{OBSERVED_DIGEST_KEY}' on the envelope does not match the "
            "canonical frozen-oracle digest recomputed from the report's own "
            f"'{OBSERVED_KEY}' object: the evidence was altered after it was "
            "written, or its digest was",
            "The observation and its digest must come from the same write; "
            "re-run the task.")

    return ReadonlyReportEvidence(
        run_id=run.run_id,
        issue_id=run.issue_id,
        request_id=getattr(run, "request_id", None),
        report_version=version,
        observed_digest=digest,
        verified_at=clock(),
    )
