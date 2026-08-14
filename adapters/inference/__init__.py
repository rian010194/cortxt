"""Repository-level concrete integrations (ADR-016: adapters/).

``inference/`` holds the concrete InferencePort backed by provider-neutral inference.
Consumed behind the kernel's port protocol; the kernel never imports this package.
"""

from .resilient_inference_port import (
    InferenceExecutionError,
    ResilientInferencePort,
)

__all__ = ["ResilientInferencePort", "InferenceExecutionError"]
