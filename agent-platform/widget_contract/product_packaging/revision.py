"""Revision identity and parent/head rules (D3-Alt-1, #606).

Revision identity is parent-chain CONTENT identity: a revision is the
canonical object

    {"package_id", "parent_revision_identity", "content"}

and ``revision_identity = sha256(canonical_object(revision))``. There is no
counter. The parent chain binds identity, so reverting A -> B -> A produces a
NEW revision identity, not a no-op. ``parent_revision_identity`` is null for
the genesis revision.

Two equivalent object forms are accepted (validate_revision): the builder
triple above, and the frozen-oracle flat form of 4a contracts.md section 3
in which the object embeds ``package_id`` + ``parent_revision_identity`` +
the packaging content fields directly (rev1 digest e0f94e0b... reproduces
ONLY for the flat form; it is the canonical export/oracle form).
"""

from __future__ import annotations

from typing import Any, Mapping

from ._digest import DigestError, digest_of_object, normalize_digest

REVISION_FIELDS = ("package_id", "parent_revision_identity", "content")

# D3-Alt-1 frozen-oracle shape (4a contracts.md section 3, Alt-1): the
# revision object ITSELF embeds parent_revision_identity plus the packaging
# content fields; there is no literal "content" wrapper field in the frozen
# examples (rev1 digest e0f94e0b... reproduces ONLY for the flat object).
# Both shapes are accepted: the triple-wrap is the module's builder form,
# the flat form is the frozen-oracle/canonical export form.
FROZEN_REVISION_FIELDS = (
    "audience",
    "evidence_refs",
    "features",
    "outcome",
    "package_id",
    "parent_revision_identity",
    "prior_binding_refs",
    "problem",
    "referenced_repositories",
    "scope",
)


class RevisionError(ValueError):
    """Raised when a revision object violates the D3-Alt-1 revision rules."""


def build_revision(
    package_id: str,
    content: Any,
    parent_revision_identity: str | None = None,
) -> dict:
    """Build a revision object, normalizing the parent digest input.

    ``parent_revision_identity`` accepts a bare-hex or ``sha256:``-prefixed
    digest and is stored as bare hex (P1-7); null means genesis.
    """
    if not isinstance(package_id, str) or not package_id:
        raise RevisionError("package_id must be a non-empty string")
    if parent_revision_identity is not None:
        try:
            parent_revision_identity = normalize_digest(
                parent_revision_identity, field="parent_revision_identity"
            )
        except DigestError as exc:
            raise RevisionError(str(exc)) from exc
    return {
        "package_id": package_id,
        "parent_revision_identity": parent_revision_identity,
        "content": content,
    }


def revision_identity(revision: Mapping[str, Any]) -> str:
    """sha256(canonical_object(revision)) per D3-Alt-1."""
    try:
        return digest_of_object(revision)
    except (TypeError, ValueError) as exc:
        raise RevisionError(f"revision object is not canonicalizable: {exc}") from exc


def candidate_digest(revision: Mapping[str, Any]) -> str:
    """Alias: the candidate digest IS the revision identity of the candidate."""
    return revision_identity(revision)


def validate_revision(revision: Mapping[str, Any]) -> None:
    """Fail-closed structural validation of a revision object."""
    if not isinstance(revision, Mapping):
        raise RevisionError("revision must be a mapping")
    if "content" in revision:
        # Builder triple form: {package_id, parent_revision_identity, content}.
        missing = [f for f in REVISION_FIELDS if f not in revision]
        if missing:
            raise RevisionError(f"revision missing fields: {', '.join(missing)}")
        extra = sorted(set(revision) - set(REVISION_FIELDS))
        if extra:
            raise RevisionError(f"revision carries undeclared fields: {', '.join(extra)}")
    else:
        # Frozen-oracle flat form (4a contracts.md section 3, Alt-1): the
        # object embeds package_id + parent_revision_identity + packaging
        # content fields directly; identity is the digest of this object.
        missing = [f for f in ("package_id", "parent_revision_identity") if f not in revision]
        if missing:
            raise RevisionError(f"revision missing fields: {', '.join(missing)}")
        extra = sorted(set(revision) - set(FROZEN_REVISION_FIELDS))
        if extra:
            raise RevisionError(f"revision carries undeclared fields: {', '.join(extra)}")
    if not isinstance(revision["package_id"], str) or not revision["package_id"]:
        raise RevisionError("package_id must be a non-empty string")
    parent = revision["parent_revision_identity"]
    if parent is not None:
        try:
            normalize_digest(parent, field="parent_revision_identity")
        except DigestError as exc:
            raise RevisionError(str(exc)) from exc


def is_genesis(revision: Mapping[str, Any]) -> bool:
    """True when the revision has no parent (genesis revision)."""
    return revision.get("parent_revision_identity") is None


def revision_chain_digest(revision: Mapping[str, Any]) -> str:
    """Content identity of a revision, bound to its parent chain (D3-Alt-1).

    Because the revision object embeds ``parent_revision_identity``, the plain
    object digest already covers the whole parent chain; reverting A -> B -> A
    yields a new identity because the parent differs. Exposed as a named rule
    so tests and callers state the intent explicitly.
    """
    return revision_identity(revision)


__all__ = [
    "REVISION_FIELDS",
    "RevisionError",
    "build_revision",
    "candidate_digest",
    "is_genesis",
    "revision_chain_digest",
    "revision_identity",
    "validate_revision",
]

# DigestError is re-exported for callers that want one exception namespace.
_ = DigestError
