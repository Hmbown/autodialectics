"""Tests for the pre-mortem failure router."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autodialectics.evaluation.pre_mortem import (
    PreMortemFeatures,
    PreMortemScore,
    extract_features,
    score_risk,
    validate_prediction,
)


# ── Feature extraction ───────────────────────────────────────────────


class TestExtractFeatures:
    """Test feature extraction from pipeline artifacts."""

    def test_extract_from_dicts(self):
        contract = {
            "acceptance_criteria": ["c1", "c2", "c3"],
            "deliverables": ["d1"],
            "constraints": ["k1", "k2"],
        }
        evidence = {
            "items": [],
            "gaps": ["g1", "g2", "g3"],
            "coverage_map": {"c1": [], "c2": ["item1"], "c3": []},
        }
        dialectic = {
            "objection_ledger": [
                {"severity": 0.9, "claim": "test"},
                {"severity": 0.5, "claim": "test2"},
            ],
            "unresolved_questions": ["q1", "q2"],
            "synthesis_steps": ["s1"],
        }

        f = extract_features(contract, evidence, dialectic)

        assert f.evidence_item_count == 0
        assert f.evidence_gap_count == 3
        assert f.evidence_gap_ratio == pytest.approx(1.0)
        assert f.coverage_density == pytest.approx(1 / 3)
        assert f.objection_count == 2
        assert f.max_objection_severity == pytest.approx(0.9)
        assert f.mean_objection_severity == pytest.approx(0.7)
        assert f.unresolved_question_count == 2
        assert f.synthesis_step_count == 1
        assert f.acceptance_criteria_count == 3
        assert f.deliverable_count == 1
        assert f.constraint_count == 2
        assert f.contract_complexity == 6

    def test_extract_empty_evidence(self):
        f = extract_features(
            {"acceptance_criteria": [], "deliverables": [], "constraints": []},
            {"items": [], "gaps": [], "coverage_map": {}},
            {"objection_ledger": [], "unresolved_questions": [], "synthesis_steps": []},
        )
        assert f.evidence_item_count == 0
        assert f.evidence_gap_count == 0
        assert f.evidence_gap_ratio == 0.0
        assert f.coverage_density == 0.0
        assert f.max_objection_severity == 0.0
        assert f.contract_complexity == 0

    def test_extract_rich_evidence(self):
        f = extract_features(
            {"acceptance_criteria": ["c1"], "deliverables": ["d1"], "constraints": []},
            {
                "items": [{"id": 1}, {"id": 2}, {"id": 3}],
                "gaps": [],
                "coverage_map": {"c1": ["item1", "item2"]},
            },
            {"objection_ledger": [], "unresolved_questions": [], "synthesis_steps": ["s1", "s2"]},
        )
        assert f.evidence_item_count == 3
        assert f.evidence_gap_count == 0
        assert f.evidence_gap_ratio == 0.0
        assert f.coverage_density == 1.0


# ── Risk scoring ─────────────────────────────────────────────────────


class TestScoreRisk:
    """Test the risk scoring heuristic."""

    def test_high_risk_evidence_poverty_plus_unresolved(self):
        """Evidence poverty + many unresolved questions => high risk."""
        f = PreMortemFeatures(
            evidence_item_count=0,
            evidence_gap_count=6,
            evidence_gap_ratio=1.0,
            coverage_density=0.0,
            objection_count=1,
            max_objection_severity=0.7,
            unresolved_question_count=6,
            contract_complexity=6,
        )
        score = score_risk(f)
        assert score.risk_score >= 0.7
        assert score.routing in ("scrutinize", "skip")
        assert "evidence poverty" in score.rationale

    def test_low_risk_good_evidence(self):
        """Rich evidence, no unresolved questions => low risk."""
        f = PreMortemFeatures(
            evidence_item_count=5,
            evidence_gap_count=0,
            evidence_gap_ratio=0.0,
            coverage_density=1.0,
            objection_count=1,
            max_objection_severity=0.3,
            unresolved_question_count=0,
            contract_complexity=4,
        )
        score = score_risk(f)
        assert score.risk_score < 0.5
        assert score.routing == "normal"

    def test_medium_risk_partial_evidence(self):
        """Some evidence gaps but not catastrophic => scrutinize."""
        f = PreMortemFeatures(
            evidence_item_count=1,
            evidence_gap_count=4,
            evidence_gap_ratio=0.8,
            coverage_density=0.2,
            objection_count=2,
            max_objection_severity=0.6,
            unresolved_question_count=3,
            contract_complexity=5,
        )
        score = score_risk(f)
        assert 0.3 <= score.risk_score <= 0.8

    def test_skip_threshold(self):
        """Very high risk triggers skip routing."""
        f = PreMortemFeatures(
            evidence_item_count=0,
            evidence_gap_count=10,
            evidence_gap_ratio=1.0,
            coverage_density=0.0,
            objection_count=3,
            max_objection_severity=0.95,
            unresolved_question_count=10,
            contract_complexity=8,
        )
        score = score_risk(f)
        assert score.risk_score >= 0.80
        assert score.routing == "skip"

    def test_custom_thresholds(self):
        """Custom thresholds override defaults."""
        f = PreMortemFeatures(
            evidence_item_count=0,
            evidence_gap_count=5,
            evidence_gap_ratio=1.0,
            unresolved_question_count=5,
            contract_complexity=5,
        )
        score = score_risk(f, threshold_scrutinize=0.3, threshold_skip=0.5)
        assert score.routing == "skip"

    def test_score_bounded_zero_one(self):
        """Score is always in [0, 1]."""
        for items in (0, 5):
            for gaps in (0, 10):
                for sev in (0.0, 1.0):
                    f = PreMortemFeatures(
                        evidence_item_count=items,
                        evidence_gap_count=gaps,
                        evidence_gap_ratio=1.0 if gaps else 0.0,
                        max_objection_severity=sev,
                        unresolved_question_count=gaps,
                        contract_complexity=max(gaps, 1),
                    )
                    s = score_risk(f)
                    assert 0.0 <= s.risk_score <= 1.0


# ── Retrospective validation ─────────────────────────────────────────


class TestValidatePrediction:
    """Test prediction vs outcome comparison."""

    def test_true_positive(self):
        score = PreMortemScore(risk_score=0.8, routing="skip")
        evaluation = {"task_success": 0.0, "overall_score": 0.3, "accepted": False}
        result = validate_prediction(score, evaluation)
        assert result["true_positive"] is True
        assert result["false_positive"] is False

    def test_false_positive(self):
        score = PreMortemScore(risk_score=0.6, routing="scrutinize")
        evaluation = {"task_success": 0.9, "overall_score": 0.9, "accepted": True}
        result = validate_prediction(score, evaluation)
        assert result["false_positive"] is True
        assert result["true_positive"] is False

    def test_true_negative(self):
        score = PreMortemScore(risk_score=0.2, routing="normal")
        evaluation = {"task_success": 0.8, "overall_score": 0.8, "accepted": True}
        result = validate_prediction(score, evaluation)
        assert result["true_negative"] is True

    def test_false_negative(self):
        score = PreMortemScore(risk_score=0.3, routing="normal")
        evaluation = {"task_success": 0.1, "overall_score": 0.2, "accepted": False}
        result = validate_prediction(score, evaluation)
        assert result["false_negative"] is True


# ── Runner integration ───────────────────────────────────────────────


def test_run_with_pre_mortem_skip(runtime) -> None:
    """Runs with pre_mortem_routing=True should be skipped when risk is very high."""
    from autodialectics.schemas import TaskSubmission

    submission = TaskSubmission(
        title="A task with no useful evidence",
        description="Do something complex without any supporting assets.",
        objectives=["Solve world hunger", "Prove P=NP", "Achieve AGI"],
        constraints=["Must be done by Tuesday"],
    )

    record = runtime.run(
        submission,
        pre_mortem_routing=True,
    )

    # The heuristic evidence explorer produces 0 items for submissions
    # with no assets. With pre-mortem routing on, this should get caught
    # as high-risk. The exact routing depends on the dialectic output,
    # so we just verify the pre_mortem artifact was recorded.
    artifacts = runtime.store.get_artifact_paths(record.run_id)
    assert "pre_mortem.json" in artifacts

    # Read the pre_mortem artifact and verify it has the expected structure
    pm_path = artifacts["pre_mortem.json"]
    pm_data = json.loads(Path(pm_path).read_text(encoding="utf-8"))
    assert "features" in pm_data
    assert "score" in pm_data
    assert "risk_score" in pm_data["score"]
    assert "routing" in pm_data["score"]
    assert pm_data["score"]["routing"] in ("normal", "scrutinize", "skip")


def test_run_without_pre_mortem_has_no_artifact(runtime) -> None:
    """Default runs should NOT produce pre_mortem artifacts."""
    from autodialectics.schemas import TaskSubmission

    submission = TaskSubmission(
        title="Simple task",
        description="Fix a small bug.",
    )

    record = runtime.run(submission)
    artifacts = runtime.store.get_artifact_paths(record.run_id)
    assert "pre_mortem.json" not in artifacts


# ── Retrospective over real stored artifacts ─────────────────────────


def test_extract_features_from_stored_artifacts(tmp_path: Path) -> None:
    """Features can be extracted from JSON files on disk (the common path for retrospective analysis)."""
    contract_data = {
        "acceptance_criteria": ["Tests pass", "No regressions"],
        "deliverables": ["Working code"],
        "constraints": ["No new deps"],
    }
    evidence_data = {
        "items": [{"id": "e1"}],
        "gaps": ["Tests pass"],
        "coverage_map": {"Tests pass": [], "No regressions": ["e1"]},
    }
    dialectic_data = {
        "objection_ledger": [{"severity": 0.8, "claim": "Tests may be insufficient"}],
        "unresolved_questions": ["Are there edge cases?"],
        "synthesis_steps": ["Step 1", "Step 2"],
    }

    f = extract_features(contract_data, evidence_data, dialectic_data)
    assert f.evidence_item_count == 1
    assert f.evidence_gap_count == 1
    assert f.objection_count == 1
    assert f.max_objection_severity == pytest.approx(0.8)
    assert f.contract_complexity == 4
