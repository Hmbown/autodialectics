"""Contract compilation: infer domain, normalize fields, build rubric, hash source."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from autodialectics.schemas import TaskContract, TaskDomain

if TYPE_CHECKING:
    from autodialectics.schemas import TaskSubmission

logger = logging.getLogger(__name__)

# ── Common forbidden shortcuts ───────────────────────────────────────

_COMMON_SHORTCUTS: list[str] = [
    "Do not claim completion without verification evidence.",
    "Do not invent citations, logs, tests, files, or benchmark results.",
    "Do not silently rewrite objectives or constraints during the run.",
    "Do not suppress uncertainty when evidence is weak or conflicting.",
    "Do not treat scratchpad notes as canonical requirements.",
]

# ── Domain-specific defaults ─────────────────────────────────────────

_DOMAIN_DEFAULTS: dict[TaskDomain, dict[str, list[str]]] = {
    TaskDomain.CODE: {
        "deliverables": [
            "Working implementation with passing tests.",
            "Documentation of design decisions and trade-offs.",
        ],
        "criteria": [
            "All tests pass on the reference interpreter/platform.",
            "No regressions in existing functionality.",
            "Code follows project style conventions.",
        ],
        "shortcuts": [
            "Do not stub out test cases or skip edge-case handling.",
            "Do not introduce dependencies without justification.",
        ],
    },
    TaskDomain.RESEARCH: {
        "deliverables": [
            "Structured findings document with cited sources.",
            "Clear distinction between established facts and inferences.",
        ],
        "criteria": [
            "Every factual claim cites a verifiable source.",
            "Contradictory evidence is acknowledged and discussed.",
        ],
        "shortcuts": [
            "Do not fabricate or hallucinate citations.",
            "Do not cherry-pick evidence to support a predetermined conclusion.",
        ],
    },
    TaskDomain.WRITING: {
        "deliverables": [
            "Revised document meeting stated quality criteria.",
            "Summary of substantive changes made.",
        ],
        "criteria": [
            "Tone and style are consistent with the brief.",
            "No factual errors introduced during revision.",
        ],
        "shortcuts": [
            "Do not pad word count without adding substantive content.",
            "Do not introduce stylistic changes that conflict with the brief.",
        ],
    },
    TaskDomain.EXPERIMENT: {
        "deliverables": [
            "Reproducible experiment protocol.",
            "Results with statistical analysis.",
        ],
        "criteria": [
            "Experimental procedure is fully specified and reproducible.",
            "Results include appropriate confidence intervals or significance tests.",
        ],
        "shortcuts": [
            "Do not fabricate experimental data or results.",
            "Do not report results without performing the described procedure.",
        ],
    },
    TaskDomain.ANALYSIS: {
        "deliverables": [
            "Structured analysis memo with supporting evidence.",
            "Clear conclusions tied to evidence.",
        ],
        "criteria": [
            "Analysis considers multiple interpretations of the data.",
            "Conclusions follow from the evidence presented.",
        ],
        "shortcuts": [
            "Do not draw conclusions not supported by available evidence.",
            "Do not ignore contradictory data points.",
        ],
    },
    TaskDomain.GENERIC: {
        "deliverables": [
            "Completed deliverable as described in objectives.",
        ],
        "criteria": [
            "Deliverable satisfies all stated objectives.",
            "Constraints are respected throughout.",
        ],
        "shortcuts": [],
    },
}

# ── Domain keyword map ───────────────────────────────────────────────

_DOMAIN_KEYWORDS: dict[TaskDomain, list[str]] = {
    TaskDomain.CODE: [
        "code", "implement", "function", "class", "module", "package",
        "library", "api", "refactor", "debug", "test", "bug",
        "compile", "deploy", "script", "program", "repository",
        "pull request", "merge", "commit", "branch",
        "fix", "error", "crash", "exception", "patch",
    ],
    TaskDomain.RESEARCH: [
        "research", "literature", "survey", "study", "citation", "reference",
        "paper", "journal", "systematic review", "meta-analysis",
        "hypothesis", "theory", "findings", "methodology",
    ],
    TaskDomain.WRITING: [
        "write", "draft", "revise", "edit", "proofread", "document",
        "article", "essay", "report", "memo", "blog", "copy",
        "narrative", "style", "tone", "voice",
    ],
    TaskDomain.EXPERIMENT: [
        "experiment", "trial", "measurement", "benchmark", "simulation",
        "hypothesis", "control", "variable", "observation", "data collection",
        "reproduce", "statistical", "significance",
    ],
    TaskDomain.ANALYSIS: [
        "analyze", "analysis", "evaluate", "assess", "compare", "investigate",
        "diagnose", "audit", "review", "examine", "data", "metrics",
        "trend", "pattern", "insight",
    ],
}

_DOMAIN_STRONG_KEYWORDS: dict[TaskDomain, list[str]] = {
    TaskDomain.CODE: [
        "implement", "refactor", "debug", "fix", "patch",
    ],
    TaskDomain.RESEARCH: [
        "research", "literature", "citation", "paper", "journal", "survey",
    ],
    TaskDomain.WRITING: [
        "write", "draft", "revise", "edit", "proofread",
    ],
    TaskDomain.EXPERIMENT: [
        "experiment", "trial", "simulation", "ablation", "data collection",
    ],
    TaskDomain.ANALYSIS: [
        "analyze", "analysis", "evaluate", "assess", "investigate", "audit",
    ],
}


class ContractCompiler:
    """Compile a TaskSubmission into a normalized TaskContract."""

    def infer_domain(self, submission: TaskSubmission) -> TaskDomain:
        """Infer domain from submission keywords, falling back to GENERIC."""
        if submission.domain is not None:
            return submission.domain

        text = " ".join([
            submission.title,
            submission.description,
            " ".join(submission.objectives),
            " ".join(submission.deliverables),
        ]).lower()

        best_domain = TaskDomain.GENERIC
        best_score = 0.0

        for domain, keywords in _DOMAIN_KEYWORDS.items():
            if domain == TaskDomain.GENERIC:
                continue
            strong_keywords = _DOMAIN_STRONG_KEYWORDS.get(domain, [])
            strong_hits = sum(1 for kw in strong_keywords if kw in text)
            weak_hits = sum(
                1 for kw in keywords
                if kw not in strong_keywords and kw in text
            )
            score = strong_hits * 3 + weak_hits
            if score > best_score:
                best_score = score
                best_domain = domain

        if best_score <= 0:
            logger.info("Domain inference inconclusive, falling back to GENERIC")
            return TaskDomain.GENERIC

        logger.info("Inferred domain: %s (score=%.2f)", best_domain, best_score)
        return best_domain

    # ── Normalizers ───────────────────────────────────────────────────

    def _normalize_objectives(
        self,
        user: list[str],
        domain: TaskDomain,
        *,
        title: str = "",
        description: str = "",
    ) -> list[str]:
        if user:
            return list(user)

        fallback = description.strip() or title.strip()
        if fallback:
            return [fallback]

        return list(user)  # Objectives come directly from user

    def _normalize_constraints(
        self, user: list[str], domain: TaskDomain
    ) -> list[str]:
        return list(user)  # Constraints come directly from user

    def _normalize_deliverables(
        self, user: list[str], domain: TaskDomain
    ) -> list[str]:
        defaults = _DOMAIN_DEFAULTS.get(domain, {}).get("deliverables", [])
        merged = list(defaults)
        for item in user:
            if item not in merged:
                merged.append(item)
        return merged

    def _normalize_acceptance_criteria(
        self, user: list[str], domain: TaskDomain
    ) -> list[str]:
        defaults = _DOMAIN_DEFAULTS.get(domain, {}).get("criteria", [])
        merged = list(defaults)
        for item in user:
            if item not in merged:
                merged.append(item)
        return merged

    def _normalize_forbidden_shortcuts(
        self, user: list[str], domain: TaskDomain
    ) -> list[str]:
        common = list(_COMMON_SHORTCUTS)
        domain_specific = _DOMAIN_DEFAULTS.get(domain, {}).get("shortcuts", [])
        merged = common + domain_specific
        for item in user:
            if item not in merged:
                merged.append(item)
        return merged

    def _normalize_workspace_root(self, workspace_root: str | None) -> str | None:
        if workspace_root is None:
            return None
        normalized = workspace_root.strip()
        return normalized or None

    def _normalize_verification_commands(
        self, commands: list[str], domain: TaskDomain
    ) -> list[str]:
        normalized: list[str] = []
        for command in commands:
            cleaned = command.strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized

    def _normalize_max_repair_attempts(
        self, attempts: int | None, domain: TaskDomain
    ) -> int:
        if attempts is None:
            return 3 if domain == TaskDomain.CODE else 1
        return max(1, attempts)

    # ── Evaluation rubric ─────────────────────────────────────────────

    def _evaluation_rubric(self, domain: TaskDomain) -> dict[str, float]:
        """Return a weighted rubric dict for the given domain."""
        base: dict[str, float] = {
            "task_success": 0.30,
            "groundedness": 0.20,
            "objection_coverage": 0.10,
            "unsupported_assertion_rate": 0.05,
            "redundancy_rate": 0.05,
            "novelty_usefulness": 0.10,
            "requirement_fidelity": 0.10,
            "verification_quality": 0.10,
        }

        if domain == TaskDomain.CODE:
            base["task_success"] = 0.35
            base["verification_quality"] = 0.15
            base["groundedness"] = 0.15
            base["novelty_usefulness"] = 0.05
        elif domain == TaskDomain.RESEARCH:
            base["groundedness"] = 0.30
            base["task_success"] = 0.20
            base["objection_coverage"] = 0.15
            base["novelty_usefulness"] = 0.10
        elif domain == TaskDomain.EXPERIMENT:
            base["verification_quality"] = 0.20
            base["groundedness"] = 0.20
            base["task_success"] = 0.25

        return base

    # ── Compile ───────────────────────────────────────────────────────

    def compile(self, submission: TaskSubmission) -> TaskContract:
        """Compile a submission into a normalized contract."""
        domain = self.infer_domain(submission)

        source_str = "|||".join([
            submission.title,
            submission.description,
            "|||".join(submission.objectives),
            "|||".join(submission.constraints),
            "|||".join(submission.deliverables),
            "|||".join(submission.acceptance_criteria),
            submission.workspace_root or "",
            "|||".join(submission.verification_commands),
            str(submission.max_repair_attempts or ""),
        ])
        source_hash = hashlib.sha256(source_str.encode()).hexdigest()

        objectives = self._normalize_objectives(
            submission.objectives,
            domain,
            title=submission.title,
            description=submission.description,
        )
        constraints = self._normalize_constraints(submission.constraints, domain)
        deliverables = self._normalize_deliverables(
            submission.deliverables, domain
        )
        criteria = self._normalize_acceptance_criteria(
            submission.acceptance_criteria, domain
        )
        shortcuts = self._normalize_forbidden_shortcuts(
            submission.forbidden_shortcuts, domain
        )
        workspace_root = self._normalize_workspace_root(submission.workspace_root)
        verification_commands = self._normalize_verification_commands(
            submission.verification_commands, domain
        )
        max_repair_attempts = self._normalize_max_repair_attempts(
            submission.max_repair_attempts, domain
        )
        rubric = self._evaluation_rubric(domain)

        notes: list[str] = []
        if not submission.objectives:
            notes.append(
                "No explicit objectives provided; seeded one from the task description/title."
            )
        if submission.domain is None:
            notes.append(f"Domain inferred as {domain.value} from keywords.")
        if workspace_root:
            notes.append(f"Execution workspace root set to {workspace_root}.")
        if verification_commands:
            notes.append(
                f"Using {len(verification_commands)} explicit verification command(s)."
            )
        if max_repair_attempts > 1:
            notes.append(
                f"Bounded repair loop enabled with max {max_repair_attempts} attempt(s)."
            )

        logger.info("Compiled contract for '%s' (domain=%s)", submission.title, domain)

        return TaskContract(
            source_hash=source_hash,
            title=submission.title,
            domain=domain,
            objectives=objectives,
            constraints=constraints,
            deliverables=deliverables,
            acceptance_criteria=criteria,
            forbidden_shortcuts=shortcuts,
            relevant_assets=submission.assets,
            workspace_root=workspace_root,
            verification_commands=verification_commands,
            max_repair_attempts=max_repair_attempts,
            evaluation_rubric=rubric,
            compiler_notes=notes,
        )
