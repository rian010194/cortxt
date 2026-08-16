"""Agent Runtime's coding loop (Fas 3 v0.1) -- the coding sibling of agent_loop.py.

claim -> materialize a disposable workspace -> baseline verification (must
fail) -> discover -> kernel (CODING_ASSISTED strategy: propose, apply+diff+
inspect scope, falsify) -> result envelope -> guaranteed cleanup. Every step
is logged to session_state, exactly like agent_loop.py, so a crash mid-run
leaves an explicit, resumable record rather than an assumed success (design
spec error-handling section, "Crash/interrupt mid-run").

Wiring notes (see the JUDGMENT CALL comments in the plan task this module was
written from for the reasoning):

- apply_patch/diff_workspace run INSIDE the inspect_scope callable injected
  into inspect_diff_against_scope, not as separate kernel operators -- the
  kernel is fixed at exactly three operators (Task 10).
- falsify_fix's two-sided check reuses the ALREADY-CAPTURED baseline result
  rather than re-running the sandbox a second time per proposal.
- fixture-declared caps are clamped to the profile's default_caps ceiling,
  never trusted at face value.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import jsonschema
import yaml

from adapters.inference.budget_gate import BudgetExhausted
from reasoning.kernel import Engine
from runtime import session_state as state
from runtime.coding.coding_profile import CODING_PROFILE
from runtime.coding.run_workspace import RunWorkspaceError, run_workspace
from runtime.coding.workspace_map import map_workspace
from runtime.execution.subprocess_sandbox import ExecutionError, ExecutionSandbox, SANDBOX_IMAGE_TAG
from runtime.execution.write_policy import WriteCaps, WritePolicyViolation, out_of_scope_paths
from runtime.text_inference_port import TextInferenceError
from runtime.tools import (
    PatchError,
    ToolAdmissionError,
    ToolGate,
    WriteGate,
    apply_patch,
    diff_workspace,
    read_workspace_file,
    run_tests,
)


def _effective_caps(fixture_caps: WriteCaps, ceiling: WriteCaps) -> WriteCaps:
    """The tighter of the fixture's declared caps and the profile's ceiling,
    field by field. A fixture may only narrow the platform's grant, never
    widen it (JUDGMENT CALL J9)."""
    return WriteCaps(
        max_files=min(fixture_caps.max_files, ceiling.max_files),
        max_bytes_per_file=min(fixture_caps.max_bytes_per_file, ceiling.max_bytes_per_file),
        max_changed_lines=min(fixture_caps.max_changed_lines, ceiling.max_changed_lines),
        max_executions=min(fixture_caps.max_executions, ceiling.max_executions),
    )


def _default_sandbox_factory(caps: WriteCaps) -> ExecutionSandbox:
    return ExecutionSandbox(image=SANDBOX_IMAGE_TAG, max_executions=caps.max_executions)


class CodingLoop:
    def __init__(self, store: Path, port, patch_schema: dict, system_prompt: str,
                 sandbox_factory: Callable[[WriteCaps], ExecutionSandbox] | None = None,
                 profile: dict | None = None) -> None:
        self._store = Path(store)
        self._port = port
        self._schema = patch_schema
        self._prompt = system_prompt
        self._sandbox_factory = sandbox_factory or _default_sandbox_factory
        self._profile = profile if profile is not None else CODING_PROFILE

    def run(self, task_id: str, fixture_dir: Path) -> dict:
        fixture_dir = Path(fixture_dir)
        session = state.create(self._store, task_id=task_id)
        session_id = session["session_id"]

        def _blocked(reason: str, sandbox: ExecutionSandbox | None = None) -> dict:
            seq = state.latest_sequence(state.load(self._store, session_id))
            state.append(self._store, session_id, seq, "session.terminal",
                         {"status": "blocked", "reason": reason})
            cost = {"sandbox_executions_used": sandbox.executions_used if sandbox else 0}
            return {"session_id": session_id, "status": "blocked", "result": None,
                    "reason": reason, "cost": cost}

        missing = set(("list_workspace", "read_workspace_file", "apply_patch",
                       "diff_workspace", "run_tests")) - set(self._profile.get("allowed_tools", []))
        if missing:
            return _blocked(f"tool admission denied: not in profile's allowed_tools: {sorted(missing)}")

        fixture = yaml.safe_load((fixture_dir / "fixture.yaml").read_text(encoding="utf-8"))
        declared_scope: list[str] = fixture["declared_scope"]
        ceiling = WriteCaps.from_mapping(self._profile.get("default_caps"))
        caps = _effective_caps(WriteCaps.from_mapping(fixture.get("caps")), ceiling)

        try:
            source = fixture_dir / fixture["workspace_dir"]
            with run_workspace(source) as ws:
                sandbox = self._sandbox_factory(caps)

                seq = state.latest_sequence(state.load(self._store, session_id))
                state.append(self._store, session_id, seq, "workspace.created",
                             {"file_count": sum(1 for _ in ws.work.rglob("*") if _.is_file())})

                # Step 3: baseline verification -- must fail, or there is no bug to fix.
                seq = state.latest_sequence(state.load(self._store, session_id))
                state.append(self._store, session_id, seq, "execution.requested", {"target": "baseline"})
                baseline_result = run_tests(sandbox, ws.baseline)
                seq = state.latest_sequence(state.load(self._store, session_id))
                state.append(self._store, session_id, seq, "execution.completed",
                             {"target": "baseline", "exit_code": baseline_result.exit_code,
                              "timed_out": baseline_result.timed_out})
                if baseline_result.exit_code == 0 and not baseline_result.timed_out:
                    return _blocked("no_bug_to_fix", sandbox)

                # Step 4: discovery.
                workspace_map = map_workspace(ws.work)
                seq = state.latest_sequence(state.load(self._store, session_id))
                state.append(self._store, session_id, seq, "discovery.completed",
                             {"file_count": workspace_map["file_count"]})

                # Step 5: context assembly.
                read_gate = ToolGate(allowed_roots=[ws.work])
                write_gate = WriteGate(allowed_roots=[ws.work])
                file_contents = {
                    f["path"]: read_workspace_file(read_gate, str(ws.work / f["path"]))
                    for f in workspace_map["files"]
                    if out_of_scope_paths([f["path"]], declared_scope) == []
                }
                content = {
                    "workspace_map": workspace_map,
                    "file_contents": file_contents,
                    "failing_test_output": (baseline_result.stdout + baseline_result.stderr),
                    "declared_scope": declared_scope,
                    "caps": {
                        "max_files": caps.max_files,
                        "max_bytes_per_file": caps.max_bytes_per_file,
                        "max_changed_lines": caps.max_changed_lines,
                        "max_executions": caps.max_executions,
                    },
                }

                captured: dict = {}

                def _propose(proposal_content):
                    seq_ = state.latest_sequence(state.load(self._store, session_id))
                    state.append(self._store, session_id, seq_, "inference.requested",
                                 {"content": proposal_content})
                    full_prompt = f"{self._prompt}\n\nInput:\n{json.dumps(proposal_content)}"
                    response = self._port.invoke(full_prompt, self._schema)
                    jsonschema.validate(instance=response, schema=self._schema)
                    seq_ = state.latest_sequence(state.load(self._store, session_id))
                    state.append(self._store, session_id, seq_, "inference.completed", {})
                    return response

                def _inspect_scope(proposal) -> bool:
                    # JUDGMENT CALL J11: apply_patch + diff_workspace live here,
                    # inside the injected callable, not as separate operators.
                    written = apply_patch(write_gate, ws.work, proposal["changes"], caps)
                    seq_ = state.latest_sequence(state.load(self._store, session_id))
                    state.append(self._store, session_id, seq_, "patch.admitted", {"paths": written})
                    seq_ = state.latest_sequence(state.load(self._store, session_id))
                    state.append(self._store, session_id, seq_, "patch.applied", {"paths": written})
                    diff_text, changed = diff_workspace(ws.baseline, ws.work)
                    captured["diff"] = diff_text
                    captured["files_changed"] = changed
                    return out_of_scope_paths(changed, declared_scope) == []

                def _verify(proposal) -> bool:
                    # JUDGMENT CALL J12: the "fails without the patch" half is the
                    # already-captured baseline_result -- no second baseline run.
                    seq_ = state.latest_sequence(state.load(self._store, session_id))
                    state.append(self._store, session_id, seq_, "execution.requested", {"target": "patched"})
                    patched_result = run_tests(sandbox, ws.work)
                    seq_ = state.latest_sequence(state.load(self._store, session_id))
                    state.append(self._store, session_id, seq_, "execution.completed",
                                 {"target": "patched", "exit_code": patched_result.exit_code,
                                  "timed_out": patched_result.timed_out})
                    captured["tests_passed"] = patched_result.exit_code == 0 and not patched_result.timed_out
                    return (
                        captured["tests_passed"]
                        and baseline_result.exit_code != 0
                        and not baseline_result.timed_out
                    )

                engine = Engine()
                try:
                    result = engine.solve_coding_assisted(
                        content=content, propose=_propose,
                        inspect_scope=_inspect_scope, verify=_verify,
                    )
                except BudgetExhausted as error:
                    return _blocked("budget_exhausted", sandbox)
                except TextInferenceError as error:
                    return _blocked(f"inference_error: {error}", sandbox)
                except jsonschema.ValidationError:
                    return _blocked("schema", sandbox)
                except (ToolAdmissionError, PatchError) as error:
                    reason = error.reason if hasattr(error, "reason") else "tool_admission_denied"
                    return _blocked(reason, sandbox)
                except WritePolicyViolation as error:
                    return _blocked(error.reason, sandbox)
                except ExecutionError as error:
                    return _blocked(error.reason, sandbox)

                if result["confidence"] < 1.0:
                    last_step = result["steps"][-1] if result["steps"] else ""
                    reason = "scope_expansion" if "scope_expansion" in last_step else "falsification_failed"
                    return _blocked(reason, sandbox)

                seq = state.latest_sequence(state.load(self._store, session_id))
                state.append(self._store, session_id, seq, "session.terminal", {"status": "succeeded"})
                return {
                    "session_id": session_id,
                    "status": "succeeded",
                    "result": {
                        "diff": captured["diff"],
                        "files_changed": captured["files_changed"],
                        "tests_passed": captured["tests_passed"],
                    },
                    "reason": None,
                    "cost": {"sandbox_executions_used": sandbox.executions_used},
                }
        except RunWorkspaceError as error:
            return _blocked(error.reason)
