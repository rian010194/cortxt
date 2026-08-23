"""Self-contained widget package export and import (.cw / JSON)."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .loader import ContractError, load_widget
from .registry import VISUAL_TOKENS_SCHEMA
from .tokens import TokensError, load_tokens
from .validation import ValidationError, validate

PACKAGE_FORMAT_VERSION = "1"

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[a-zA-Z0-9_-]{10,}"),
    re.compile(r"cfat_[a-zA-Z0-9_-]{10,}"),
    re.compile(r"ghp_[a-zA-Z0-9_-]{10,}"),
    re.compile(r"github_pat_[a-zA-Z0-9_-]{10,}"),
    re.compile(r"-----BEGIN\s+[A-Z\s]+KEY-----"),
)


class PackageError(ValueError):
    """Raised when a widget package export, import, or validation fails."""
    pass


def scan_for_secrets(val: Any) -> list[str]:
    """Recursively scan an object for secret-shaped strings.

    Returns a list of match descriptions if any pattern matches.
    """
    matches: list[str] = []

    def _walk(item: Any, path: str) -> None:
        if isinstance(item, str):
            for pat in SECRET_PATTERNS:
                if pat.search(item):
                    matches.append(f"{path}: matches pattern {pat.pattern}")
        elif isinstance(item, Mapping):
            for k, v in item.items():
                if isinstance(k, str):
                    for pat in SECRET_PATTERNS:
                        if pat.search(k):
                            matches.append(f"{path}.<key:{k}>: key matches pattern {pat.pattern}")
                _walk(v, f"{path}.{k}")
        elif isinstance(item, (list, tuple, set)):
            for idx, elem in enumerate(item):
                _walk(elem, f"{path}[{idx}]")

    _walk(val, "$")
    return matches


def assert_no_secrets(content: Any, label: str = "package") -> None:
    """Fail-closed check ensuring content carries no secret-shaped markers."""
    findings = scan_for_secrets(content)
    if findings:
        raise PackageError(f"Secret-shaped content detected in {label}: {findings[0]}")


def _resolve_ap_path(ap_path: str | Path | None = None) -> Path:
    if ap_path is not None:
        return Path(ap_path)
    return Path(__file__).resolve().parents[1]


def _find_spec_path(widget_id: str, ap_path: Path) -> Path | None:
    """Locate the YAML spec file for a widget ID."""
    manifest_path = ap_path / "widget" / "widgets.json"
    if manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            widgets = data.get("widgets", [])
            for w in widgets:
                if isinstance(w, dict) and w.get("id") == widget_id:
                    spec_rel = w.get("spec")
                    if not spec_rel:
                        return None
                    for candidate in [ap_path / spec_rel, ap_path / "widget" / spec_rel]:
                        if candidate.is_file():
                            return candidate
        except Exception:
            pass

    # Search widget_contract/specs and widget/specs directories
    for search_dir in [ap_path / "widget_contract" / "specs", ap_path / "widget" / "specs"]:
        if not search_dir.is_dir():
            continue
        for name in (
            f"{widget_id}.yaml",
            f"{widget_id}.yml",
            f"{widget_id}-0.1.yaml",
            f"{widget_id}-0.1.yml",
        ):
            candidate = search_dir / name
            if candidate.is_file():
                return candidate

        # Also inspect YAML specs inside the directory to match widget.id
        for candidate in search_dir.glob("*.yaml"):
            try:
                w_obj = load_widget(candidate.read_bytes())
                if w_obj.id == widget_id:
                    return candidate
            except Exception:
                continue

    return None


def _find_fixture_data(widget_id: str, ap_path: Path) -> dict[str, Any] | None:
    """Locate fixture or current artifact data for a widget ID."""
    manifest_path = ap_path / "widget" / "widgets.json"
    artifact_name: str | None = None
    if manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            for w in data.get("widgets", []):
                if isinstance(w, dict) and w.get("id") == widget_id:
                    artifact_name = w.get("artifact")
                    break
        except Exception:
            pass

    candidates: list[Path] = []
    if artifact_name:
        candidates.extend([
            ap_path / "widget" / artifact_name,
            ap_path / "widget" / "fixtures" / artifact_name,
        ])
    candidates.extend([
        ap_path / "widget" / f"{widget_id}.json",
        ap_path / "widget" / "fixtures" / f"{widget_id}.json",
    ])

    for cand in candidates:
        if cand.is_file():
            try:
                return json.loads(cand.read_text(encoding="utf-8"))
            except Exception:
                continue
    return None


def export_package(
    widget_id: str,
    *,
    out_path: str | Path | None = None,
    tokens_path: str | Path | None = None,
    ap_path: str | Path | None = None,
) -> dict[str, Any]:
    """Bundle a widget into a single self-contained package.

    Parameters:
        widget_id: Widget identifier (e.g. candidates, pulse, map, docker, webhooks).
        out_path: Optional path to write the package JSON (.cw).
        tokens_path: Optional path to custom tokens.json.
        ap_path: Optional path to agent-platform directory.

    Returns:
        Package dictionary.

    Raises:
        PackageError: If widget is unknown, missing spec/tokens, fails validation, or contains secrets.
    """
    ap = _resolve_ap_path(ap_path)

    manifest_path = ap / "widget" / "widgets.json"
    if manifest_path.is_file():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            for entry in manifest_data.get("widgets", []):
                if isinstance(entry, dict) and entry.get("id") == widget_id:
                    if entry.get("spec") is None:
                        raise PackageError(f"Widget '{widget_id}' has no declared spec file to export")
        except PackageError:
            raise
        except Exception:
            pass

    spec_file = _find_spec_path(widget_id, ap)
    if spec_file is None or not spec_file.is_file():
        raise PackageError(f"Widget '{widget_id}' not found in manifest or spec directory")

    try:
        spec_text = spec_file.read_text(encoding="utf-8")
    except Exception as err:
        raise PackageError(f"Failed to read spec file {spec_file}: {err}") from err

    try:
        widget_obj = load_widget(spec_text)
    except ContractError as err:
        raise PackageError(f"Widget spec {spec_file} failed strict validation: {err}") from err

    try:
        tokens_data = load_tokens(tokens_path)
    except TokensError as err:
        raise PackageError(f"Tokens validation failed: {err}") from err

    renderer_file = ap / "widget" / "maker.js"
    if not renderer_file.is_file():
        renderer_file = ap.parents[0] / "site" / "public" / "widgets" / "maker.js"
    if not renderer_file.is_file():
        raise PackageError(f"Renderer file maker.js not found at {renderer_file}")

    try:
        renderer_text = renderer_file.read_text(encoding="utf-8")
    except Exception as err:
        raise PackageError(f"Failed to read renderer file {renderer_file}: {err}") from err

    fixture_data = _find_fixture_data(widget_id, ap)

    manifest = {
        "package_format_version": PACKAGE_FORMAT_VERSION,
        "widget_id": widget_obj.id,
        "widget_version": widget_obj.version,
        "title": widget_obj.title,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "tokens_version": "visual-tokens.v1",
    }

    pkg: dict[str, Any] = {
        "package_format": PACKAGE_FORMAT_VERSION,
        "manifest": manifest,
        "widget": spec_text,
        "tokens": tokens_data,
        "renderer": renderer_text,
    }
    if fixture_data is not None:
        pkg["fixture"] = fixture_data

    assert_no_secrets(pkg, f"exported widget package '{widget_id}'")

    if out_path is not None:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        descriptor, tmp_path_str = tempfile.mkstemp(prefix=".package-", suffix=".tmp", dir=out.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as f:
                json.dump(pkg, f, indent=2, ensure_ascii=True)
            os.replace(tmp_path_str, out)
        except Exception as err:
            if os.path.exists(tmp_path_str):
                os.remove(tmp_path_str)
            raise PackageError(f"Failed to write package to {out}: {err}") from err

    return pkg


def validate_package(package_data: Any) -> dict[str, Any]:
    """Strict fail-closed validation of a package dictionary.

    Returns:
        Validated dictionary with resolved widget model.

    Raises:
        PackageError: If format, required fields, contract, tokens, or secret check fails.
    """
    if not isinstance(package_data, dict):
        raise PackageError("Package root must be a JSON object")

    fmt = package_data.get("package_format")
    if fmt is None and isinstance(package_data.get("manifest"), dict):
        fmt = package_data["manifest"].get("package_format_version")

    if fmt != PACKAGE_FORMAT_VERSION:
        raise PackageError(
            f"Unsupported package format version: '{fmt}' (expected '{PACKAGE_FORMAT_VERSION}')"
        )

    for field in ("widget", "tokens", "renderer"):
        if field not in package_data:
            raise PackageError(f"Package missing required field: '{field}'")

    assert_no_secrets(package_data, "package")

    renderer = package_data["renderer"]
    if not isinstance(renderer, str) or not renderer.strip():
        raise PackageError("Package renderer must be a non-empty string")

    tokens = package_data["tokens"]
    if not isinstance(tokens, dict):
        raise PackageError("Package tokens must be an object")
    try:
        validate(tokens, VISUAL_TOKENS_SCHEMA)
    except ValidationError as err:
        raise PackageError(f"Package tokens failed schema validation: {err}") from err

    spec_text = package_data["widget"]
    if not isinstance(spec_text, str) or not spec_text.strip():
        raise PackageError("Package widget spec must be a non-empty string")
    try:
        widget_obj = load_widget(spec_text)
    except ContractError as err:
        raise PackageError(f"Package widget spec failed strict validation: {err}") from err

    if "fixture" in package_data and package_data["fixture"] is not None:
        if not isinstance(package_data["fixture"], (dict, list)):
            raise PackageError("Package fixture must be a JSON object or array")

    return {
        "widget_model": widget_obj,
        "package": package_data,
    }


def load_package(
    package_input: str | Path | dict[str, Any],
    *,
    target_dir: str | Path | None = None,
    ap_path: str | Path | None = None,
) -> dict[str, Any]:
    """Validate and install a widget package into a target widget directory.

    Fail-closed: If validation fails, zero files are written and the manifest is untouched.

    Returns:
        Dictionary with installed paths and widget identity.

    Raises:
        PackageError: If package is malformed, missing required fields, fails contract validation, or contains secrets.
    """
    if isinstance(package_input, dict):
        package_data = package_input
    elif isinstance(package_input, (str, Path)):
        p = Path(package_input)
        if p.is_file():
            try:
                raw = p.read_text(encoding="utf-8")
                package_data = json.loads(raw)
            except json.JSONDecodeError as err:
                raise PackageError(f"Malformed JSON in package file {p}: {err}") from err
            except Exception as err:
                raise PackageError(f"Failed to read package file {p}: {err}") from err
        elif isinstance(package_input, str) and package_input.strip().startswith("{"):
            try:
                package_data = json.loads(package_input)
            except json.JSONDecodeError as err:
                raise PackageError(f"Malformed JSON in package content: {err}") from err
        else:
            raise PackageError(f"Package file not found: {p}")
    else:
        raise PackageError("Invalid package input type: expected dict, Path, or JSON string")

    validated = validate_package(package_data)
    widget_obj = validated["widget_model"]

    if target_dir is not None:
        widget_dir = Path(target_dir)
    else:
        ap = _resolve_ap_path(ap_path)
        widget_dir = ap / "widget"

    widget_dir.mkdir(parents=True, exist_ok=True)
    specs_dir = widget_dir / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)

    spec_filename = f"{widget_obj.id}-{widget_obj.version}.yaml"
    spec_path = specs_dir / spec_filename
    spec_path.write_text(package_data["widget"], encoding="utf-8")

    artifact_path: Path | None = None
    if "fixture" in package_data and package_data["fixture"] is not None:
        artifact_filename = f"{widget_obj.id}.json"
        artifact_path = widget_dir / artifact_filename
        artifact_path.write_text(json.dumps(package_data["fixture"], indent=2, ensure_ascii=True), encoding="utf-8")

    manifest_path = widget_dir / "widgets.json"
    manifest_data: dict[str, Any] = {"widgets": []}
    if manifest_path.is_file():
        try:
            loaded_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded_manifest, dict) and isinstance(loaded_manifest.get("widgets"), list):
                manifest_data = loaded_manifest
        except Exception:
            manifest_data = {"widgets": []}

    rel_spec = f"specs/{spec_filename}"
    widgets_list = manifest_data.setdefault("widgets", [])
    existing = next((w for w in widgets_list if isinstance(w, dict) and w.get("id") == widget_obj.id), None)
    if existing:
        existing["title"] = widget_obj.title
        existing["spec"] = rel_spec
        existing["artifact"] = f"{widget_obj.id}.json"
        existing["hint"] = f"cortxt widget --view {widget_obj.id}"
    else:
        widgets_list.append({
            "id": widget_obj.id,
            "title": widget_obj.title,
            "spec": rel_spec,
            "artifact": f"{widget_obj.id}.json",
            "hint": f"cortxt widget --view {widget_obj.id}",
        })

    manifest_path.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=True), encoding="utf-8")

    return {
        "widget_id": widget_obj.id,
        "widget_version": widget_obj.version,
        "title": widget_obj.title,
        "spec_path": str(spec_path),
        "manifest_path": str(manifest_path),
        "artifact_path": str(artifact_path) if artifact_path else None,
    }
