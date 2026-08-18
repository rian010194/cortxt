"""Hard resource bounds for the RLM engine (target architecture §11.2)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RLMConfig:
    """Every RLM run must carry these hard limits (fail-closed when exceeded)."""

    max_depth: int = 2                 # was 4 — dispatch contract §19.1
    max_branches_per_node: int = 3
    max_total_children: int = 6        # was 12 — dispatch contract §19.1
    max_model_invocations: int = 20
    max_context_reads: int = 30
    max_runtime_seconds: float = 60.0
    max_cost: float = 1.0
    max_output_size: int = 4096
    explicit_stop_policy: bool = True

    def validate(self) -> None:
        """Fail-fast if any bound is malformed (a config must be sane).

        A value of 0 is legal for a budget field: it means "no allowance allowed"
        and yields an immediate fail-closed stop (useful for testing and for
        hard policy gates). Negative values are always invalid.
        """
        nonneg = {
            "max_depth": self.max_depth,
            "max_branches_per_node": self.max_branches_per_node,
            "max_total_children": self.max_total_children,
            "max_model_invocations": self.max_model_invocations,
            "max_context_reads": self.max_context_reads,
            "max_cost": self.max_cost,
            "max_output_size": self.max_output_size,
        }
        for name, v in nonneg.items():
            if v < 0:
                raise ValueError(f"{name} must be >= 0, got {v}")
        if self.max_runtime_seconds < 0:
            raise ValueError(f"max_runtime_seconds must be >= 0, got {self.max_runtime_seconds}")
