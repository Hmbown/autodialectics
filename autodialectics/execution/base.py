"""Abstract base class for execution adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autodialectics.dialectic.engine import DialecticalPlanner
    from autodialectics.routing.cliproxy import ModelClient
    from autodialectics.schemas import (
        DialecticArtifact,
        EvidenceBundle,
        ExecutionArtifact,
        TaskContract,
    )


class ExecutionAdapter(ABC):
    """Base interface for domain-specific execution adapters.

    Each adapter is responsible for constructing the appropriate prompts
    and interpreting the model response into an ExecutionArtifact.
    """

    name: str = "base"

    @abstractmethod
    def execute(
        self,
        contract: TaskContract,
        evidence: EvidenceBundle,
        dialectic: DialecticArtifact,
        model_client: ModelClient,
        policy_surfaces: dict[str, str] | None = None,
    ) -> ExecutionArtifact:
        """Execute the task given the contract, evidence, and dialectic plan.

        Parameters
        ----------
        contract : TaskContract
            The compiled task contract.
        evidence : EvidenceBundle
            Context evidence from exploration.
        dialectic : DialecticArtifact
            The dialectical plan (thesis/antithesis/synthesis).
        model_client : ModelClient
            Client for LLM completion.
        policy_surfaces : dict[str, str], optional
            Policy prompt surfaces (thesis/antithesis/synthesis templates).

        Returns
        -------
        ExecutionArtifact
            The execution result.
        """
        ...
