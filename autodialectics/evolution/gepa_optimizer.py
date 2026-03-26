"""Champion-challenger evolution: GEPA optimization and policy promotion."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from autodialectics.schemas import PolicySnapshot
from autodialectics.utils.dspy import build_dspy_lm

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

    def __init__(self, store: SqliteStore, settings: Any | None = None) -> None:
        self.store = store
        self.settings = settings


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
        if self.settings is None:
            logger.debug("No settings provided; cannot configure DSPy GEPA")
            return None

        try:
            import dspy  # type: ignore[import-untyped]

            # Extract insights from reports
            insights = self._extract_insights(reports)

            train_set = self._build_gepa_trainset(dspy, reports)
            if not train_set:
                return None

            base_thesis = champion.surfaces.get(
                "thesis", DEFAULT_POLICY_SURFACES["thesis"]
            )
            reflection_lm = build_dspy_lm(
                self.settings,
                temperature=1.0,
                max_tokens=1200,
            )

            class ThesisSignature(dspy.Signature):  # type: ignore[misc]
                """Generate a step-by-step plan for a task."""

                task: str = dspy.InputField()
                description: str = dspy.InputField()
                failure_focus: str = dspy.InputField()
                plan: str = dspy.OutputField()

            try:
                with dspy.context(lm=reflection_lm):
                    student = dspy.ChainOfThought(
                        ThesisSignature.with_instructions(base_thesis)
                    )
                    metric = self._build_gepa_metric(dspy, insights)
                    optimizer = dspy.GEPA(
                        metric=metric,
                        max_metric_calls=4,
                        reflection_lm=reflection_lm,
                        num_threads=1,
                        track_stats=True,
                        use_merge=False,
                        warn_on_score_mismatch=False,
                    )
                    optimized = optimizer.compile(
                        student,
                        trainset=train_set[:5],
                        valset=train_set[:3] or train_set[:5],
                    )
                optimized_instruction = self._extract_gepa_instruction(
                    optimized,
                    fallback=base_thesis,
                )
                new_surfaces = dict(champion.surfaces)
                new_surfaces["thesis"] = self._merge_gepa_instruction(
                    optimized_instruction,
                    insights,
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
        except Exception as exc:
            logger.debug("GEPA optimization failed before compile: %s", exc)
            return None

    def _build_gepa_trainset(
        self,
        dspy: Any,
        reports: list[dict[str, Any]],
    ) -> list[Any]:
        """Translate benchmark reports into a small GEPA trainset."""
        train_set: list[Any] = []
        for report in reports:
            submission = report.get("submission", {})
            if not submission:
                continue

            failure_focus = self._report_failure_focus(report)
            train_set.append(
                dspy.Example(
                    task=str(submission.get("title", "")),
                    description=str(submission.get("description", "")),
                    failure_focus=failure_focus,
                ).with_inputs("task", "description", "failure_focus")
            )
        return train_set

    def _build_gepa_metric(
        self,
        dspy: Any,
        insights: list[str],
    ):
        """Create a DSPy 3.x-compatible GEPA feedback metric."""
        global_terms = self._salient_terms(" ".join(insights))

        def metric(
            gold: Any,
            pred: Any,
            trace: Any = None,
            pred_name: str | None = None,
            pred_trace: Any = None,
        ) -> Any:
            plan_text = str(getattr(pred, "plan", "")).lower()
            local_terms = self._salient_terms(
                str(getattr(gold, "failure_focus", ""))
            )
            target_terms = local_terms or global_terms

            coverage_hits = sum(
                1 for term in target_terms if term in plan_text
            )
            coverage = coverage_hits / max(len(target_terms), 1)
            verification_bonus = 0.0
            if any(
                token in plan_text
                for token in ("verify", "verification", "test", "evidence", "check")
            ):
                verification_bonus = 0.25

            score = min(0.15 + coverage * 0.6 + verification_bonus, 1.0)

            feedback_parts: list[str] = []
            if target_terms and coverage < 0.6:
                feedback_parts.append(
                    "Explicitly address these observed failure modes: "
                    + ", ".join(target_terms[:6])
                    + "."
                )
            if verification_bonus == 0.0:
                feedback_parts.append(
                    "Add concrete verification, testing, or evidence-checking steps."
                )
            if pred_name:
                feedback_parts.append(
                    f"Optimize the `{pred_name}` instruction to front-load correctness checks."
                )

            feedback = " ".join(feedback_parts) or (
                "Keep the plan concrete, verification-heavy, and aligned to observed failure modes."
            )
            return dspy.Prediction(score=score, feedback=feedback)

        return metric

    @staticmethod
    def _extract_gepa_instruction(optimized: Any, fallback: str) -> str:
        """Extract the optimized predictor instruction from a DSPy module."""
        for _, predictor in optimized.named_predictors():
            instructions = getattr(predictor.signature, "instructions", "")
            if instructions:
                return str(instructions).strip()
        return fallback

    def _merge_gepa_instruction(
        self,
        optimized_instruction: str,
        insights: list[str],
    ) -> str:
        """Preserve the optimized instruction while anchoring it to recent failures."""
        merged = optimized_instruction.strip()
        missing = [
            insight for insight in insights[:3]
            if insight not in merged
        ]
        if not missing:
            return merged

        lines = "\n".join(f"- {insight}" for insight in missing)
        return (
            f"{merged}\n\n"
            "Recent benchmark failure signals to account for:\n"
            f"{lines}"
        )

    def _report_failure_focus(self, report: dict[str, Any]) -> str:
        """Collapse report notes into a compact optimization target."""
        parts: list[str] = []
        notes = report.get("notes", [])
        for note in notes[:3]:
            if isinstance(note, str) and note.strip():
                parts.append(note.strip())

        unmet = report.get("unmet_criteria", [])
        if unmet:
            unique_unmet = sorted({str(item) for item in unmet if item})
            if unique_unmet:
                parts.append("Unmet criteria: " + ", ".join(unique_unmet))

        slop = report.get("slop", {})
        if isinstance(slop, dict):
            high_slop = [
                f"{key}={value:.2f}"
                for key, value in slop.items()
                if isinstance(value, (int, float)) and value >= 0.3
            ]
            if high_slop:
                parts.append("High slop signals: " + ", ".join(high_slop))

        return " ".join(parts)

    @staticmethod
    def _salient_terms(text: str) -> list[str]:
        """Extract a stable list of important lexical targets from feedback text."""
        seen: set[str] = set()
        ordered_terms: list[str] = []
        for raw in text.lower().replace(":", " ").replace(",", " ").split():
            term = raw.strip("().;[]{}!?")
            if len(term) < 5:
                continue
            if term in seen:
                continue
            seen.add(term)
            ordered_terms.append(term)
        return ordered_terms[:8]

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
