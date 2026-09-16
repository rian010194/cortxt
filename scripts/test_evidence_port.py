#!/usr/bin/env python3
"""Deterministic regression tests for scripts/evidence_port.py (W-4, #614).

No network, no git, no hermes: the gate is pure over a Run record and a
result envelope. Run directly: python scripts/test_evidence_port.py
(0 = pass). Colocated self-running check-script convention (one pytest entry
point).
"""
import importlib.util
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# dispatcher.py first, registered under its import name so evidence_port.py's
# `from commit_evidence import CorrelationFailure` (and the test's own import
# of commit_evidence) resolve exactly as the production chain resolves them.
d_spec = importlib.util.spec_from_file_location("dispatcher", REPO / "scripts" / "dispatcher.py")
d = importlib.util.module_from_spec(d_spec)
sys.modules["dispatcher"] = d
d_spec.loader.exec_module(d)

import commit_evidence as ce  # noqa: E402 - scripts/ is sys.path[0] for this script

ep_spec = importlib.util.spec_from_file_location("evidence_port", REPO / "scripts" / "evidence_port.py")
ep = importlib.util.module_from_spec(ep_spec)
sys.modules["evidence_port"] = ep
ep_spec.loader.exec_module(ep)

fail = []


def check(name, cond, detail=""):
    print(f"  {'ok' if cond else 'FAIL':4} {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fail.append(name)


def make_run(mutating=False, request_id="req-1"):
    return d.Run(
        run_id="run-e1", issue_id="o/r#1", workflow="wf/v1", worker_role="observer",
        runtime="hermes-readonly", claimed_at=100.0, lease_seconds=60,
        mutating=mutating, request_id=request_id,
    )


def observation(**overrides):
    """A realistic W-3 `PackagingOpsApi.workstream()` projection shape."""
    obs = {
        "schema_version": 1,
        "status": "ok",
        "workstream": {"id": "WS-606", "issue_id": "rian010194/cortxt#606", "number": 606},
        "counts": {"revisions": 2, "operations": 4, "decisions": 1, "evidence": 3},
        "store_backup_status": "declared-unfulfilled",
    }
    obs.update(overrides)
    return obs


def good_envelope(run, obs=None, **envelope_overrides):
    payload = {
        "completed": True,
        "failed": False,
        "report_version": 1,
        "observed": observation() if obs is None else obs,
    }
    envelope = {
        "run_id": run.run_id,
        "issue_id": run.issue_id,
        "request_id": run.request_id,
        "report_state": "completed",
        "report_payload": payload,
        "observed_digest": ep.observed_digest(payload["observed"]),
    }
    envelope.update(envelope_overrides)
    return envelope


def refusal_of(outcome):
    return outcome if isinstance(outcome, ce.CorrelationFailure) else None


def run_all_checks():
    print("== cross-layer canon check: the port's canonicalization matches the packaging digest form ==")
    # Frozen-oracle canonicalization is owned by
    # widget_contract.product_packaging._digest.canonical_object. When the
    # packaging layer is importable (worktree venv), the digest must match it
    # byte-for-byte, not merely be self-consistent (the wrong-form digest the
    # W-2b review called out is self-consistent and cross-layer useless).
    try:
        from widget_contract.product_packaging import _digest as packaging_digest
        imported = True
    except Exception:  # noqa: BLE001 - scripts-only interpreter still runs the rest
        imported = False
        print("  (packaging layer not importable in this interpreter; "
              "self-consistency checks still run)")
    if imported:
        check("digest of an observation equals the packaging layer's digest",
              ep.observed_digest(observation())
              == packaging_digest.digest_of_object(observation()))
        check("digest of a nested observation equals the packaging layer's digest",
              ep.observed_digest({"a": [1, {"b": "c"}], "z": None})
              == packaging_digest.digest_of_object({"a": [1, {"b": "c"}], "z": None}))
        check("canonical form is the documented one (sorted, compact, ASCII, default=str)",
              packaging_digest.canonical_object({"k": "vård", "n": 1})
              == '{"k":"v\\u00e5rd","n":1}')

    print("== digest: canonicalization and normalization ==")
    # Vector from the documented rules: json.dumps(obj, sort_keys=True,
    # separators=(",", ":"), ensure_ascii=True, default=str), UTF-8, no
    # trailing newline.
    check("observed_digest returns 64-hex for a plain observation",
          isinstance(ep.observed_digest(observation()), str)
          and len(ep.observed_digest(observation())) == 64)
    check("key order does not change the digest",
          ep.observed_digest({"a": 1, "b": 2}) == ep.observed_digest({"b": 2, "a": 1}))
    check("content change changes the digest (tamper is detectable)",
          ep.observed_digest(observation()) != ep.observed_digest(observation(counts={})))
    check("default=str form matches the computed manual vector",
          ep.observed_digest({"when": "2026-09-16", "ok": True})
          == "168d79c6979b9ac4930c6990ffd15a64a75a96dba10ad112169af4295167d135")
    check("None observation has no digest",
          ep.observed_digest(None) is None)
    circular = {}
    circular["self"] = circular
    check("unserializable observation has no digest (fail closed)",
          ep.observed_digest(circular) is None)

    print("== verify_readonly_report: a verified report is durable evidence ==")
    run = make_run()
    outcome = ep.verify_readonly_report(run, good_envelope(run), clock=lambda: 123.0)
    check("a complete, correlated, digest-matching report verifies", not refusal_of(outcome),
          repr(refusal_of(outcome)))
    check("evidence carries the observation digest",
          outcome.observed_digest == ep.observed_digest(observation()))
    check("evidence carries the Run's identity", outcome.run_id == run.run_id
          and outcome.issue_id == run.issue_id and outcome.request_id == "req-1")
    check("evidence carries the report version", outcome.report_version == 1)
    check("evidence is timestamped by the injected clock", outcome.verified_at == 123.0)
    check("as_record is the durable shape", outcome.as_record()["observed_digest"]
          == outcome.observed_digest)

    print("== correlation first, exactly like the mutating gate ==")
    run_nr = make_run(request_id=None)
    env_nr = good_envelope(run_nr)
    env_nr.pop("request_id")
    r = refusal_of(ep.verify_readonly_report(run_nr, env_nr))
    check("a Run record without request_id is refused, not skipped",
          r is not None and r.code == "request_id_not_recorded", repr(r))
    env_no_req = good_envelope(run)
    env_no_req.pop("request_id")
    r = refusal_of(ep.verify_readonly_report(run, env_no_req))
    check("envelope missing request_id is refused",
          r is not None and r.code == "request_correlation_mismatch", repr(r))
    r = refusal_of(ep.verify_readonly_report(run, good_envelope(run, run_id="other-run")))
    check("mismatched run_id is refused",
          r is not None and r.code == "run_correlation_mismatch", repr(r))
    r = refusal_of(ep.verify_readonly_report(run, good_envelope(run, issue_id="o/r#2")))
    check("mismatched issue_id is refused",
          r is not None and r.code == "issue_correlation_mismatch", repr(r))

    print("== the whole channel, re-checked settlement-side ==")
    r = refusal_of(ep.verify_readonly_report(run, good_envelope(run, report_state=None)))
    check("report_state=None (runtime never started) is refused",
          r is not None and r.code == ep.READONLY_FAILURE, repr(r))
    r = refusal_of(ep.verify_readonly_report(
        run, good_envelope(run, report_state="requested_but_missing")))
    check("a missing report is refused", r is not None and r.code == ep.READONLY_FAILURE)
    r = refusal_of(ep.verify_readonly_report(
        run, good_envelope(run, report_state="unreadable")))
    check("an unreadable report is refused", r is not None)
    r = refusal_of(ep.verify_readonly_report(
        run, good_envelope(run, report_state="invalid")))
    check("an invalid report is refused", r is not None)
    r = refusal_of(ep.verify_readonly_report(
        run, good_envelope(run, report_state="incomplete")))
    check("an incomplete report is refused", r is not None)

    print("== the carried payload, re-checked settlement-side ==")
    r = refusal_of(ep.verify_readonly_report(run, good_envelope(run, report_payload=None)))
    check("a completed state with no carried payload is refused", r is not None
          and r.code == ep.READONLY_FAILURE)
    r = refusal_of(ep.verify_readonly_report(
        run, good_envelope(run, report_payload={"completed": True, "failed": False,
                                                "report_version": 2,
                                                "observed": observation()})))
    check("an unimplemented report_version is refused", r is not None)
    r = refusal_of(ep.verify_readonly_report(
        run, good_envelope(run, report_payload={"completed": "true", "failed": False,
                                                "report_version": 1,
                                                "observed": observation()})))
    check("`completed: \"true\"` is refused (truthiness stays closed)", r is not None)
    r = refusal_of(ep.verify_readonly_report(
        run, good_envelope(run, report_payload={"completed": True, "failed": True,
                                                "report_version": 1,
                                                "observed": observation()})))
    check("`failed: true` is refused", r is not None)

    print("== the observation and its digest ==")
    env_no_obs = good_envelope(run)
    env_no_obs["report_payload"] = {"completed": True, "failed": False,
                                    "report_version": 1}
    r = refusal_of(ep.verify_readonly_report(run, env_no_obs))
    check("a report with no observation key is refused", r is not None
          and r.code == ep.READONLY_FAILURE, repr(r))
    r = refusal_of(ep.verify_readonly_report(run, good_envelope(run, obs={})))
    check("an empty observation is refused", r is not None)
    r = refusal_of(ep.verify_readonly_report(
        run, good_envelope(run, observed_digest=None)))
    check("an envelope whose digest was dropped is refused", r is not None
          and r.code == ep.READONLY_FAILURE, repr(r))
    r = refusal_of(ep.verify_readonly_report(
        run, tampered_observation(run)))
    check("a tampered observation (content changed, digest kept) is refused", r is not None,
          repr(r))
    r = refusal_of(ep.verify_readonly_report(
        run, tampered_digest(run)))
    check("a swapped digest (content kept) is refused", r is not None, repr(r))
    check("every refusal carries the stable unreadable-report code",
          refusal_of(ep.verify_readonly_report(run, tampered_digest(run))).code
          == "readonly_report_unverifiable")

    print("== admission control: refused families never verify ==")
    r = refusal_of(ep.verify_readonly_report(run, {}))
    check("an empty envelope is refused", r is not None and r.code == "run_correlation_mismatch")
    check("a non-mutating run's verified evidence is independent of its mutating flag",
          not refusal_of(ep.verify_readonly_report(make_run(mutating=True),
                                                   good_envelope(make_run()))))

    print("== gate markers documented ==")
    check("success marker named", ep.EVIDENCE_GATE_READONLY == "readonly_report_correlated")
    check("failure marker named", ep.READONLY_GATE_FAILED == "readonly_report_failed")
    check("refusal code named", ep.READONLY_FAILURE == "readonly_report_unverifiable")


def tampered_observation(run):
    env = good_envelope(run)
    env["report_payload"] = {**env["report_payload"],
                             "observed": observation(counts={"revisions": 999})}
    return env


def tampered_digest(run):
    env = good_envelope(run)
    env["observed_digest"] = "f" * 64
    return env


def test_all_checks_pass():
    """Pytest entry point: run the same checks as the standalone script."""
    run_all_checks()
    assert not fail, f"{len(fail)} check(s) failed: {fail}"


if __name__ == "__main__":
    run_all_checks()
    if fail:
        print(f"\n{len(fail)} check(s) failed: {fail}")
        sys.exit(1)
    print("\nall checks passed")
    sys.exit(0)
