"""Operator-facing discovery and conversational orchestration helpers.

Discovery intentionally reads names and filesystem presence only.  Skill
instruction bodies, runtime configuration, credentials, and user prompts are
outside this module's boundary.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


def discover_skills(
    roots: Iterable[tuple[str, Path]],
    *,
    loaded_by_root: dict[Path, str] | None = None,
) -> list[dict[str, Any]]:
    """Discover skill names without publishing instruction bodies or secrets."""
    skills: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source, root in roots:
        if not root.is_dir():
            continue
        try:
            manifests = sorted(root.rglob("SKILL.md"))
        except OSError:
            continue
        for manifest in manifests:
            name = manifest.parent.name
            key = (source, name)
            if key in seen:
                continue
            seen.add(key)
            loaded_profile = (loaded_by_root or {}).get(root)
            skills.append(
                {
                    "skill_id": name,
                    "source": source,
                    "installed": True,
                    "available": True,
                    "loaded": loaded_profile is not None,
                    "loaded_by": [loaded_profile] if loaded_profile else [],
                    "running": False,
                }
            )
    return skills


def default_skill_roots(agent_platform_path: Path) -> list[tuple[str, Path]]:
    home = Path.home()
    roots = [
        ("cortxt", agent_platform_path / "skills"),
        ("hermes", home / "AppData" / "Local" / "hermes" / "skills"),
        ("claude-code", home / ".claude" / "skills"),
        ("claude-plugin", home / ".claude" / "plugins" / "cache"),
        ("codex", home / ".codex" / "skills"),
    ]
    configured = os.environ.get("CORTXT_SKILLS_DIR")
    if configured:
        roots.insert(0, ("cortxt-configured", Path(configured)))
    return roots


def hermes_profile_skill_roots() -> tuple[list[tuple[str, Path]], dict[Path, str]]:
    """Return profile skill roots and their profile identities, metadata only."""
    profiles_root = Path.home() / "AppData" / "Local" / "hermes" / "profiles"
    roots: list[tuple[str, Path]] = []
    loaded: dict[Path, str] = {}
    if not profiles_root.is_dir():
        return roots, loaded
    try:
        profiles = sorted(path for path in profiles_root.iterdir() if path.is_dir())
    except OSError:
        return roots, loaded
    for profile in profiles:
        root = profile / "skills"
        if root.is_dir():
            roots.append(("hermes-profile", root))
            loaded[root] = profile.name
    return roots, loaded


def merge_skills(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge duplicate manifests without collapsing their source/runtime state."""
    merged: dict[str, dict[str, Any]] = {}
    for item in items:
        key = str(item["skill_id"])
        target = merged.setdefault(
            key,
            {
                "skill_id": key,
                "sources": [],
                "installed": False,
                "available": False,
                "loaded": False,
                "loaded_by": [],
                "running": False,
            },
        )
        source = item.get("source")
        if source and source not in target["sources"]:
            target["sources"].append(source)
        for flag in ("installed", "available", "loaded", "running"):
            target[flag] = bool(target[flag] or item.get(flag))
        for profile in item.get("loaded_by", []):
            if profile not in target["loaded_by"]:
                target["loaded_by"].append(profile)
    return sorted(merged.values(), key=lambda item: item["skill_id"].casefold())


_PROFILE_ROW = re.compile(
    r"^\s*(?P<active>[◆*]?)\s*(?P<name>[\w-]+)\s+(?P<model>\S+)\s+"
    r"(?P<gateway>running|stopped|unknown)(?:\s|$)",
    re.IGNORECASE,
)
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def parse_hermes_profiles(output: str) -> list[dict[str, Any]]:
    """Parse the stable human table without reading profile config files."""
    profiles: list[dict[str, Any]] = []
    for line in output.splitlines():
        line = _ANSI_ESCAPE.sub("", line)
        # Hermes emits UTF-8 table glyphs, while Windows may decode captured
        # subprocess output with the active ANSI code page ("◆" -> "â—†").
        try:
            line = line.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        match = _PROFILE_ROW.match(line)
        if not match:
            continue
        profiles.append(
            {
                "profile_id": match.group("name"),
                "runtime_id": "hermes",
                "model": match.group("model").strip(),
                "loaded": bool(match.group("active")),
                "running": match.group("gateway").lower() == "running",
                "status": match.group("gateway").lower(),
            }
        )
    return profiles


def discover_hermes_profiles(
    *, run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
) -> list[dict[str, Any]]:
    """Best-effort Hermes profile discovery through its public CLI."""
    try:
        result = run(
            ["hermes", "profile", "list"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_hermes_profiles(result.stdout) if result.returncode == 0 else []


_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*\S+"),
    re.compile(r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_-]{12,}\b"),
)


def sanitize_user_text(value: str, *, max_chars: int = 4096) -> tuple[str, int]:
    """Redact common inline secrets before constructing an external prompt."""
    sanitized = value
    hits = 0
    for pattern in _SECRET_PATTERNS:
        sanitized, count = pattern.subn("[REDACTED]", sanitized)
        hits += count
    return sanitized[:max_chars], hits


def build_chat_prompt(user_text: str, projection: dict[str, Any]) -> tuple[str, int]:
    sanitized, redactions = sanitize_user_text(user_text)
    compact = {
        "orchestrator": projection.get("orchestrator", {}),
        "workstreams": [
            {
                "id": item.get("workstream_id"),
                "status": item.get("status"),
                "branch": (item.get("workspace") or {}).get("branch"),
                "lanes": [
                    {
                        "label": lane.get("label"),
                        "runtime": lane.get("runtime"),
                        "status": lane.get("status"),
                    }
                    for lane in item.get("lanes", [])[:12]
                ],
            }
            for item in projection.get("workstreams", [])[:12]
        ],
        "runtimes": [
            {
                "id": item.get("runtime_id"),
                "installed": item.get("installed", False),
                "running": item.get("running", False),
            }
            for item in projection.get("runtimes", [])
        ],
        "skills": {
            "installed": sum(bool(item.get("installed")) for item in projection.get("skills", [])),
            "loaded": sum(bool(item.get("loaded")) for item in projection.get("skills", [])),
            "running": sum(bool(item.get("running")) for item in projection.get("skills", [])),
        },
    }
    prompt = (
        "You are the local Cortxt orchestrator. Answer only what the operator actually asked. "
        "Do not volunteer a status briefing, workstream list, options menu, or next actions for "
        "a greeting or general conversation. Use operational state only when the operator asks "
        "about state, work, agents, or next steps. Never recompute, estimate, or paraphrase numeric "
        "totals; quote an exact supplied field or omit the number. Give concise, advisory guidance. "
        "GitHub workflow state is authoritative. Never claim you executed, approved, merged, "
        "deployed, or closed anything. Ask before proposing a state-changing dispatch.\n\n"
        f"SANITIZED LOCAL PROJECTION:\n{json.dumps(compact, ensure_ascii=False)}\n\n"
        f"OPERATOR:\n{sanitized}"
    )
    return prompt, redactions


def local_conversation_reply(value: str) -> str | None:
    """Handle trivial social turns locally: no model cost and no state disclosure."""
    normalized = re.sub(r"[^\wåäö]+", " ", value.casefold()).strip()
    greetings = {
        "hello", "hi", "hey", "hello there", "hi there",
        "hej", "hallå", "tjena", "god morgon", "god kväll",
    }
    if normalized not in greetings:
        return None
    if normalized in {"hello", "hi", "hey", "hello there", "hi there"}:
        return "Hello! I’m the Cortxt orchestrator. What would you like to work on?"
    return "Hej! Jag är Cortxt-orkestratorn. Vad vill du arbeta med?"


def transcript_record(
    *, transcript_id: str, turn_index: int, role: str, content: str,
    engine: str, status: str, redactions: int = 0,
    engine_session_id: str | None = None,
) -> dict[str, Any]:
    return {
        "transcript_id": transcript_id,
        "turn_index": turn_index,
        "role": role,
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content_chars": len(content),
        "engine": engine,
        "status": status,
        "redactions": redactions,
        "engine_session_id": engine_session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def new_transcript_id() -> str:
    return str(uuid.uuid4())


def engine_inventory(manifests, context) -> list[dict[str, Any]]:
    return [
        {
            "engine_id": manifest.engine_id,
            "task_shapes": list(manifest.task_shapes),
            "cost_class": manifest.cost_class,
            "reliability_class": manifest.reliability_class,
            "checkpoint_required": manifest.checkpoint_required,
            "invoker_registered": context.get(manifest.engine_id).has_provider,
        }
        for manifest in manifests
    ]


def render_overview(summary, workstreams, runtimes, engines, skills) -> str:
    lines = [
        "CORTXT ORCHESTRATOR",
        "=" * 72,
        f"State: {summary['status']} -- {summary['message']}",
        (
            "Agent sessions: "
            f"{summary['active_agent_sessions']} active, "
            f"{summary['stale_agent_sessions']} stale, "
            f"{summary['blocked_agent_sessions']} blocked, "
            f"{summary['failed_agent_sessions']} failed"
        ),
        "",
        "WORKSTREAMS",
    ]
    if not workstreams:
        lines.append("  No workstreams found.")
    for item in workstreams[:10]:
        branch = item["workspace"].get("branch") or "no branch metadata"
        lines.append(
            f"  {item['workstream_id']}: {item['status']} | {len(item['lanes'])} lane(s) | {branch}"
        )
    lines.extend(["", "ENGINES"])
    for engine in engines:
        invocation = "ready" if engine["invoker_registered"] else "manual"
        lines.append(
            f"  {engine['engine_id']}: {engine['reliability_class']} | invoke={invocation} | "
            f"checkpoint={'yes' if engine['checkpoint_required'] else 'no'}"
        )
    lines.extend(["", "RUNTIMES"])
    for runtime in runtimes:
        lines.append(f"  {runtime['runtime_id']}: {'installed' if runtime['installed'] else 'missing'}")
    lines.extend(["", f"SKILLS: {len(skills)} discovered (metadata only)"])
    if not skills:
        lines.append("  No readable skill roots were discovered.")
    else:
        by_source: dict[str, int] = {}
        for skill in skills:
            sources = skill.get("sources") or [skill.get("source", "unknown")]
            for source in sources:
                by_source[source] = by_source.get(source, 0) + 1
        for source, count in sorted(by_source.items()):
            lines.append(f"  {source}: {count}")
    return "\n".join(lines)


def render_chat_command(command: str, projection: dict[str, Any]) -> str:
    """Render deterministic REPL commands without invoking an engine."""
    if command == "/status":
        summary = projection["orchestrator"]
        return (
            f"{summary['status']}: {summary['message']} | "
            f"{len(projection.get('workstreams', []))} workstream(s)"
        )
    if command == "/workstreams":
        items = projection.get("workstreams", [])
        return "\n".join(
            f"{item['workstream_id']} | {item['status']} | "
            f"{(item.get('workspace') or {}).get('branch') or 'no branch'}"
            for item in items
        ) or "No workstreams found."
    if command == "/runtimes":
        rows = []
        for item in projection.get("runtimes", []):
            states = [
                name for name in ("installed", "available", "loaded", "running")
                if item.get(name)
            ]
            rows.append(f"{item['runtime_id']} | {', '.join(states) or 'unavailable'}")
        return "\n".join(rows) or "Runtime inventory unavailable."
    if command == "/skills":
        items = projection.get("skills", [])
        installed = sum(bool(item.get("installed")) for item in items)
        loaded = sum(bool(item.get("loaded")) for item in items)
        running = sum(bool(item.get("running")) for item in items)
        sources = sorted({source for item in items for source in item.get("sources", [])})
        return (
            f"{len(items)} skills: {installed} installed, {loaded} loaded, "
            f"{running} running | sources: {', '.join(sources) or 'none'}"
        )
    return "Unknown command. Use /status, /workstreams, /runtimes, /skills, or /quit."
