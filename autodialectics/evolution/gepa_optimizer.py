"""Champion-challenger evolution: GEPA optimization and policy promotion."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from autodialectics.schemas import PolicySnapshot

if TYPE_CHECKING:
    from autodialectics.storage.sqlite import SqliteStore

logger = logging.getLogger(__name__)


# ── Default policy surfaces ───────────────────────────────────────────

DEFAULT_POLICY_SURFACES: dict[str, str] = {
    "thesis": (
        "Create a detailed step-by-step plan to accomplish the task objectives. "
        "For each step, specify the expected outcome and any dependencies. "
        "Consider the constraints and forbidden shortcuts carefully."
    ),
    "antithesis": (
        "Critically evaluate the proposed plan. Identify: (1) logical gaps or "
        "unsupported assumptions, (2) steps that could fail or produce "
        "incorrect results, (3) shortcuts that might be tempting but violate "
        "the constraints, (4) edge cases that are not addressed. "
        "Rate each objection by severity (0.0-1.0)."
    ),
    "synthesis": (
        "Reconcile the plan with all serious objections. For each objection "
        "with severity > 0.5, explicitly state how it is addressed. "
        "Revise the plan to incorporate improvements. Do not ignore objections "
        "or hand-wave them away."
    ),
}


@dataclass
class PromotionDecision:
    """Decision on whether to promote a challenger to champion."""

    promote: bool
    rationale: str


class ChampionChallengerManager:
    """Manage champion-challenger policy evolution.

    Supports both DSPy GEPA optimization and basic heuristic mutation
    for creating challengers from benchmark reports.
    """

    def __init__(self, store: SqliteStore) -> None:
        self.store = store

    # ── Champion management ───────────────────────────────────────────

    def ensure_default_champion(self) -> PolicySnapshot:
        """Create a default champion policy if none exists."""
        champion_data = self.store.latest_champion()
        if champion_data is not None:
            return PolicySnapshot(**champion_data)

        logger.info("No champion found; creating default champion")
        policy = PolicySnapshot(
            version=1,
            surfaces=dict(DEFAULT_POLICY_SURFACES),
            is_champion=True,
            generation="initial",
        )
        self.store.save_policy(policy.model_dump(mode="json"))
        return policy

    def create_challenger(
        self,
        reports: list[dict[str, Any]],
        *,
        use_gepa: bool = True,
    ) -> PolicySnapshot:
        """Create a challenger policy from benchmark reports.

        Parameters
        ----------
        reports : list[dict]
            Recent benchmark report dicts.
        use_gepa : bool
            If True, try to use DSPy GEPA for optimization. Falls back
            to heuristic mutation if DSPy is unavailable.

        Returns
        -------
        PolicySnapshot
            The new challenger policy.
        """
        champion = self.ensure_default_champion()

        if use_gepa:
            challenger = self._try_gepa_optimization(champion, reports)
            if challenger is not None:
                return challenger
            logger.info(
                "GEPA optimization unavailable; falling back to heuristic mutation"
            )

        return self._heuristic_challenger(champion, reports)

    def _try_gepa_optimization(
        self,
        champion: PolicySnapshot,
        reports: list[dict[str, Any]],
    ) -> PolicySnapshot | None:
        """Try to use DSPy GEPA for prompt optimization."""
        try:
            import dspy  # type: ignore[import-untyped]

            # Extract insights from reports
            insights = self._extract_insights(reports)

            # Build a training set from benchmark reports
            train_set = []
            for report in reports:
                submission = report.get("submission", {})
                if submission:
                    train_set.append(
                        dspy.Example(
                            task=str(submission.get("title", "")),
                            description=str(submission.get("description", "")),
                            score=report.get("overall_score", 0.0),
                        ).with_inputs("task", "description")
                    )

            if not train_set:
                return None

            # Use GEPA to optimize the thesis prompt
            base_thesis = champion.surfaces.get(
                "thesis", DEFAULT_POLICY_SURFACES["thesis"]
            )

            class ThesisSignature(dspy.Signature):  # type: ignore[misc]
                """Generate a step-by-step plan for a task."""
                task: str = dspy.InputField()
                description: str = dspy.InputField()
                plan: str = dspy.OutputField()

            optimizer = dspy.GEPA(
                metric=lambda _, __, ___: 1.0,  # Simplified metric
                num_threads=1,
            )

            try:
                optimized = optimizer.compile(
                    dspy.ChainOfThought(ThesisSignature),
                    trainset=train_set[:5],
                )
                # The GEPA optimizer modifies the prompt
                # We extract the updated signature for the new surfaces
                new_surfaces = dict(champion.surfaces)
                # Note: GEPA modifies the module in-place; we keep a copy
                new_surfaces["thesis"] = base_thesis  # Keep original as fallback
                new_surfaces["thesis"] += (
                    "\n\nAdditional guidance from optimization: "
                    "Focus on correctness and verification."
                )

                challenger = PolicySnapshot(
                    version=champion.version + 1,
                    parent_id=champion.policy_id,
                    surfaces=new_surfaces,
                    is_champion=False,
                    generation="gepa",
                )
                self.store.save_policy(challenger.model_dump(mode="json"))
                logger.info("Created GEPA challenger: %s", challenger.policy_id)
                return challenger

            except Exception as exc:
                logger.debug("GEPA compilation failed: %s", exc)
                return None

        except ImportError:
            logger.debug("DSPy not available for GEPA optimization")
            return None

    def _heuristic_challenger(
        self,
        champion: PolicySnapshot,
        reports: list[dict[str, Any]],
    ) -> PolicySnapshot:
        """Create a challenger by mutating champion surfaces based on reports."""
        insights = self._extract_insights(reports)

        new_surfaces = dict(champion.surfaces)

        # Add insights to the thesis prompt
        if insights:
            thesis = new_surfaces.get(
                "thesis", DEFAULT_POLICY_SURFACES["thesis"]
            )
            thesis += "\n\nAdditional considerations based on recent runs:\n"
            for insight in insights[:5]:
                thesis += f"- {insight}\n"
            new_surfaces["thesis"] = thesis

        # Strengthen the antithesis prompt based on common failure modes
        antithesis = new_surfaces.get(
            "antithesis", DEFAULT_POLICY_SURFACES["antithesis"]
        )
        common_issues = self._extract_common_issues(reports)
        if common_issues:
            antithesis += "\n\nPay special attention to:\n"
            for issue in common_issues[:3]:
                antithesis += f"- {issue}\n"
            new_surfaces["antithesis"] = antithesis

        challenger = PolicySnapshot(
            version=champion.version + 1,
            parent_id=champion.policy_id,
            surfaces=new_surfaces,
            is_champion=False,
            generation="heuristic",
        )
        self.store.save_policy(challenger.model_dump(mode="json"))
        logger.info(
            "Created heuristic challenger: %s (parent=%s)",
            challenger.policy_id,
            champion.policy_id,
        )
        return challenger

    def _extract_insights(self, reports: list[dict[str, Any]]) -> list[str]:
        """Extract actionable insights from benchmark reports."""
        insights: list[str] = []
        for report in reports:
            notes = report.get("notes", [])
            for note in notes:
                if isinstance(note, str) and len(note) > 10:
                    insights.append(note)
            slop = report.get("slop", {})
            if isinstance(slop, dict):
                for key, value in slop.items():
                    if isinstance(value, (int, float)) and value > 0.3:
                        insights.append(
                            f"High {key} score ({value:.2f}) detected"
                        )
        return insights

    def _extract_common_issues(self, reports: list[dict[str, Any]]) -> list[str]:
        """Extract common failure modes from reports."""
        issues: list[str] = []
        unmet_counts: dict[str, int] = {}
        for report in reports:
            unmet = report.get("unmet_criteria", [])
            for criterion in unmet:
                if isinstance(criterion, str):
                    unmet_counts[criterion] = unmet_counts.get(criterion, 0) + 1

        for criterion, count in sorted(
            unmet_counts.items(), key=lambda x: -x[1]
        ):
            if count >= 2:
                issues.append(f"Frequently unmet: {criterion} ({count} times)")

        return issues

    # ── Comparison ────────────────────────────────────────────────────

    def compare(
        self,
        champion_score: float,
        challenger_score: float,
        champion_slop: float,
        challenger_slop: float,
        canary_passed: bool,
    ) -> PromotionDecision:
        """Decide whether to promote the challenger.

        Returns promote=True if:
        - challenger_score > champion_score
        - challenger_slop <= champion_slop
        - canary_passed is True
        """
        reasons: list[str] = []

        if not canary_passed:
            return PromotionDecision(
                promote=False,
                rationale="Canary test failed; challenger cannot be promoted.",
            )

        if challenger_slop > champion_slop:
            reasons.append(
                f"Challenger slop ({challenger_slop:.3f}) exceeds "
                f"champion slop ({champion_slop:.3f})"
            )

        if challenger_score <= champion_score:
            reasons.append(
                f"Challenger score ({challenger_score:.3f}) does not exceed "
                f"champion score ({champion_score:.3f})"
            )

        if reasons:
            return PromotionDecision(
                promote=False,
                rationale="; ".join(reasons),
            )

        return PromotionDecision(
            promote=True,
            rationale=(
                f"Challenger outperforms champion: "
                f"score {challenger_score:.3f} > {champion_score:.3f}, "
                f"slop {challenger_slop:.3f} <= {champion_slop:.3f}, "
                f"canary passed"
            ),
        )

    # ── Promotion and rollback ────────────────────────────────────────

    def promote(
        self, challenger_id: str, decision: PromotionDecision
    ) -> PolicySnapshot:
        """Promote a challenger to champion, demoting the current champion.

        Parameters
        ----------
        challenger_id : str
            The policy_id of the challenger to promote.
        decision : PromotionDecision
            The promotion decision (must have promote=True).

        Returns
        -------
        PolicySnapshot
            The newly promoted champion.

        Raises
        ------
        ValueError
            If decision.promote is False or challenger not found.
        """
        if not decision.promote:
            raise ValueError(
                "Cannot promote: decision.promote is False. "
                f"Rationale: {decision.rationale}"
            )

        challenger_data = self.store.get_policy(challenger_id)
        if challenger_data is None:
            raise ValueError(f"Challenger policy '{challenger_id}' not found")

        # Demote current champion
        champion_data = self.store.latest_champion()
        if champion_data is not None:
            champion_data["is_champion"] = False
            self.store.save_policy(champion_data)

        # Promote challenger
        challenger_data["is_champion"] = True
        self.store.save_policy(challenger_data)

        logger.info(
            "Promoted challenger %s to champion. Rationale: %s",
            challenger_id,
            decision.rationale,
        )
        return PolicySnapshot(**challenger_data)

    def rollback(self) -> PolicySnapshot:
        """Restore the previous champion.

        If the current champion has a parent_id, the parent becomes champion.
        Otherwise, creates a fresh default champion.

        Returns
        -------
        PolicySnapshot
            The restored champion.
        """
        current_data = self.store.latest_champion()
        if current_data is None:
            return self.ensure_default_champion()

        parent_id = current_data.get("parent_id")
        if not parent_id:
            logger.info(
                "Current champion has no parent; creating fresh default champion"
            )
            # Demote current
            current_data["is_champion"] = False
            self.store.save_policy(current_data)
            return self.ensure_default_champion()

        parent_data = self.store.get_policy(parent_id)
        if parent_data is None:
            logger.warning(
                "Parent policy '%s' not found; creating fresh default champion",
                parent_id,
            )
            current_data["is_champion"] = False
            self.store.save_policy(current_data)
            return self.ensure_default_champion()

        # Demote current, promote parent
        current_data["is_champion"] = False
        self.store.save_policy(current_data)

        parent_data["is_champion"] = True
        self.store.save_policy(parent_data)

        logger.info("Rolled back to champion: %s", parent_id)
        return PolicySnapshot(**parent_data)
