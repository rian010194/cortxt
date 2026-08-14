"""Embedding surface + deterministic stub for testability (target §12)."""

from __future__ import annotations

import hashlib
from typing import Callable

# An embedding maps a node (by id) to a fixed-size float vector.
EmbeddingFn = Callable[[str], list[float]]

_EMBED_DIM = 8


def _stable_vector(text: str, dim: int = _EMBED_DIM) -> list[float]:
    """Deterministic hash-based vector so distances are reproducible (no model).

    Each of ``dim`` bytes of the SHA-256 of ``text`` seeds one coordinate in
    [0,1). This is purely a test harness for geometries; a real model embedding
    would replace this later via the same EmbeddingFn surface.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    vec = []
    for i in range(dim):
        vec.append((digest[i] / 255.0) * 2.0 - 1.0)  # normalize to [-1,1]
    return vec


def hash_embedding(node_id: str) -> list[float]:
    """Default reproducible stub embedding keyed on node id."""
    return _stable_vector(node_id)


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [0,1] (clamped), 1.0 when identical."""
    import math

    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-9
    nb = math.sqrt(sum(y * y for y in b)) or 1e-9
    return max(0.0, min(1.0, dot / (na * nb)))
