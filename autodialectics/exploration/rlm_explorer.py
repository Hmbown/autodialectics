"""Context exploration: heuristic search or DSPy-guided recursive long-context exploration."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from autodialectics.schemas import AssetKind, EvidenceBundle, EvidenceItem
from autodialectics.utils.dspy import dspy_lm_context
from autodialectics.utils.text import chunk_text, overlap_score

if TYPE_CHECKING:
    from autodialectics.schemas import AssetRef, TaskContract

logger = logging.getLogger(__name__)


class ContextExplorer:
    """Explore task assets to build an EvidenceBundle for downstream planning."""

    def __init__(
        self,
        *,
        use_dspy_rlm: bool = False,
        max_evidence_items: int = 20,
        rlm_threshold_chars: int = 8000,
        dspy_settings: Any | None = None,
        rlm_max_depth: int = 2,
        rlm_leaf_chars: int = 2200,
        rlm_branch_factor: int = 2,
    ) -> None:
        self.use_dspy_rlm = use_dspy_rlm
        self.max_evidence_items = max_evidence_items
        self.rlm_threshold_chars = rlm_threshold_chars
        self.dspy_settings = dspy_settings
        self.rlm_max_depth = max(1, rlm_max_depth)
        self.rlm_leaf_chars = max(800, rlm_leaf_chars)
        self.rlm_branch_factor = max(1, rlm_branch_factor)

    # ── Public API ────────────────────────────────────────────────────

    def explore(
        self,
        contract: TaskContract,
        queries: list[str] | None = None,
    ) -> EvidenceBundle:
        """Load assets and explore them to build an evidence bundle."""
        queries = queries or self._default_queries(contract)
        assets = contract.relevant_assets

        if not assets:
            return EvidenceBundle(
                summary="No assets provided; evidence bundle is empty.",
            )

        loaded = self._load_assets(assets)
        if not loaded:
            return EvidenceBundle(
                summary="Assets were specified but could not be loaded.",
            )

        total_chars = sum(len(text) for _, text in loaded)
        use_rlm = (
            self.use_dspy_rlm
            and total_chars > self.rlm_threshold_chars
        )

        items: list[EvidenceItem] = []
        coverage_map: dict[str, list[str]] = {q: [] for q in queries}
        generated_with_rlm = False

        for query in queries:
            if use_rlm:
                try:
                    result = self._explore_with_dspy_rlm(loaded, query)
                    if result:
                        items.extend(result)
                        generated_with_rlm = True
                    else:
                        logger.warning(
                            "DSPy RLM produced no evidence for query '%s', falling back to lexical recursion",
                            query,
                        )
                        result = self._explore_recursively(loaded, query)
                        items.extend(result)
                except Exception:
                    logger.warning(
                        "DSPy RLM failed for query '%s', falling back to recursive",
                        query,
                    )
                    result = self._explore_recursively(loaded, query)
                    items.extend(result)
            else:
                result = self._explore_recursively(loaded, query)
                items.extend(result)

            for item in result:
                coverage_map.setdefault(item.query, []).append(
                    item.evidence_id
                )

        # Deduplicate and limit
        seen: set[tuple[str, str, str]] = set()
        unique_items: list[EvidenceItem] = []
        for item in items:
            key = (
                item.asset_id,
                item.query,
                item.excerpt.strip(),
            )
            if key not in seen:
                seen.add(key)
                unique_items.append(item)
        unique_items = unique_items[: self.max_evidence_items]

        gaps = [
            q for q, ids in coverage_map.items() if not ids
        ]

        return EvidenceBundle(
            summary=f"Explored {len(assets)} assets, found {len(unique_items)} evidence items.",
            generated_with_rlm=generated_with_rlm,
            items=unique_items,
            coverage_map=coverage_map,
            gaps=gaps,
        )

    def _default_queries(self, contract: TaskContract) -> list[str]:
        """Derive exploration queries from the compiled contract instead of a generic placeholder."""
        candidates = [contract.title, *contract.objectives]
        candidates.extend(contract.acceptance_criteria)
        candidates.extend(contract.constraints[:2])
        candidates.extend(contract.deliverables[:2])

        queries: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            cleaned = candidate.strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            queries.append(cleaned)
            if len(queries) >= 8:
                break

        return queries or ["What is the main task and context?"]

    # ── Asset loading ─────────────────────────────────────────────────

    def _load_assets(
        self, assets: list[AssetRef]
    ) -> list[tuple[str, str]]:
        """Load assets into (label, text) pairs."""
        loaded: list[tuple[str, str]] = []
        for asset in assets:
            label = asset.label or asset.asset_id
            text = None

            if asset.kind == AssetKind.INLINE_TEXT:
                text = asset.text or ""

            elif asset.kind == AssetKind.FILE:
                if asset.location:
                    try:
                        text = Path(asset.location).read_text(
                            encoding="utf-8"
                        )
                    except Exception as exc:
                        logger.warning(
                            "Failed to load file '%s': %s",
                            asset.location,
                            exc,
                        )

            elif asset.kind == AssetKind.JSON:
                if asset.text:
                    try:
                        obj = json.loads(asset.text)
                        text = json.dumps(obj, indent=2)
                    except json.JSONDecodeError:
                        text = asset.text
                elif asset.location:
                    try:
                        raw = Path(asset.location).read_text(
                            encoding="utf-8"
                        )
                        obj = json.loads(raw)
                        text = json.dumps(obj, indent=2)
                    except Exception as exc:
                        logger.warning(
                            "Failed to load JSON '%s': %s",
                            asset.location,
                            exc,
                        )

            elif asset.kind == AssetKind.DIRECTORY:
                if asset.location:
                    try:
                        dir_path = Path(asset.location)
                        parts: list[str] = []
                        for fp in sorted(dir_path.rglob("*")):
                            if fp.is_file():
                                try:
                                    parts.append(
                                        f"--- {fp.relative_to(dir_path)} ---\n"
                                        + fp.read_text(encoding="utf-8")
                                    )
                                except Exception:
                                    pass
                        text = "\n\n".join(parts)
                    except Exception as exc:
                        logger.warning(
                            "Failed to load directory '%s': %s",
                            asset.location,
                            exc,
                        )

            if text is not None:
                loaded.append((label, text))

        return loaded

    # ── Recursive (heuristic) explorer ────────────────────────────────

    def _explore_recursively(
        self,
        loaded: list[tuple[str, str]],
        query: str,
    ) -> list[EvidenceItem]:
        """Keyword-overlap scoring on chunks; no LLM required."""
        items: list[EvidenceItem] = []
        query_tokens = set(query.lower().split())

        for source_path, text in loaded:
            chunks = chunk_text(text)
            for idx, chunk in enumerate(chunks):
                score = overlap_score(query, chunk)
                if score > 0.05:
                    items.append(
                        EvidenceItem(
                            asset_id=source_path,
                            query=query,
                            source_path=source_path,
                            excerpt=chunk[:800],
                            rationale=f"Keyword overlap score: {score:.3f}",
                            weight=score,
                        )
                    )

        items.sort(key=lambda x: x.weight, reverse=True)
        return items[: self.max_evidence_items]

    # ── DSPy RLM explorer ─────────────────────────────────────────────

    def _explore_with_dspy_rlm(
        self,
        loaded: list[tuple[str, str]],
        query: str,
    ) -> list[EvidenceItem]:
        """Use DSPy to recursively narrow long context and extract evidence."""
        items: list[EvidenceItem] = []
        with dspy_lm_context(
            self.dspy_settings,
            temperature=0.2,
            max_tokens=900,
        ) as (dspy, _):
            for source_path, text in loaded:
                try:
                    items.extend(
                        self._recursive_rlm_explore(
                            dspy=dspy,
                            source_path=source_path,
                            text=text,
                            query=query,
                            depth=0,
                            node_suffix="root",
                        )
                    )
                except Exception as exc:
                    logger.debug("RLM source %s failed: %s", source_path, exc)

        items.sort(key=lambda x: x.weight, reverse=True)
        return items[: self.max_evidence_items]

    def _recursive_rlm_explore(
        self,
        *,
        dspy: Any,
        source_path: str,
        text: str,
        query: str,
        depth: int,
        node_suffix: str,
    ) -> list[EvidenceItem]:
        """Recursively narrow the search space before extracting evidence."""
        segment = text.strip()
        if not segment:
            return []

        if depth >= self.rlm_max_depth or len(segment) <= self.rlm_leaf_chars:
            item = self._extract_rlm_evidence(
                dspy=dspy,
                source_path=source_path,
                query=query,
                segment=segment,
                node_suffix=node_suffix,
                fallback_weight=overlap_score(query, segment),
            )
            return [item] if item is not None else []

        scored_segments: list[tuple[float, int, str, str]] = []
        for idx, child in enumerate(self._split_text_for_rlm(segment)):
            score, rationale = self._score_rlm_segment(
                dspy=dspy,
                query=query,
                segment=child,
            )
            if score > 0.12:
                scored_segments.append((score, idx, child, rationale))

        if not scored_segments:
            return []

        scored_segments.sort(key=lambda entry: entry[0], reverse=True)
        results: list[EvidenceItem] = []

        for score, idx, child, rationale in scored_segments[: self.rlm_branch_factor]:
            child_suffix = f"{node_suffix}.d{depth}s{idx}"
            if depth + 1 >= self.rlm_max_depth or len(child) <= self.rlm_leaf_chars or score >= 0.82:
                item = self._extract_rlm_evidence(
                    dspy=dspy,
                    source_path=source_path,
                    query=query,
                    segment=child,
                    node_suffix=child_suffix,
                    fallback_weight=score,
                    rationale_hint=rationale,
                )
                if item is not None:
                    results.append(item)
            else:
                results.extend(
                    self._recursive_rlm_explore(
                        dspy=dspy,
                        source_path=source_path,
                        text=child,
                        query=query,
                        depth=depth + 1,
                        node_suffix=child_suffix,
                    )
                )

        return results

    def _score_rlm_segment(
        self,
        *,
        dspy: Any,
        query: str,
        segment: str,
    ) -> tuple[float, str]:
        """Ask the LM which segment deserves deeper inspection."""

        class SegmentSelection(dspy.Signature):  # type: ignore[misc]
            """Judge whether a segment is promising for deeper recursive exploration."""

            query: str = dspy.InputField(desc="Exploration query")
            segment: str = dspy.InputField(desc="Candidate context segment")
            relevance: str = dspy.OutputField(
                desc="A float from 0.0 to 1.0 estimating how promising this segment is"
            )
            rationale: str = dspy.OutputField(
                desc="Why the segment should or should not be explored further"
            )

        judge = dspy.ChainOfThought(SegmentSelection)
        result = judge(query=query, segment=segment[:5000])
        score = self._coerce_score(
            getattr(result, "relevance", ""),
            fallback=overlap_score(query, segment),
        )
        rationale = str(getattr(result, "rationale", "")).strip()
        return score, rationale

    def _extract_rlm_evidence(
        self,
        *,
        dspy: Any,
        source_path: str,
        query: str,
        segment: str,
        node_suffix: str,
        fallback_weight: float,
        rationale_hint: str = "",
    ) -> EvidenceItem | None:
        """Extract concrete evidence from a recursively selected segment."""

        class EvidenceExtraction(dspy.Signature):  # type: ignore[misc]
            """Extract the strongest evidence passage from a focused long-context segment."""

            query: str = dspy.InputField(desc="Exploration query")
            segment: str = dspy.InputField(desc="Focused segment of the full context")
            evidence: str = dspy.OutputField(
                desc="The most relevant evidence excerpt, or an empty string if none is present"
            )
            rationale: str = dspy.OutputField(
                desc="Why this evidence helps answer the query"
            )
            confidence: str = dspy.OutputField(
                desc="A float from 0.0 to 1.0 describing confidence in the extracted evidence"
            )

        extractor = dspy.ChainOfThought(EvidenceExtraction)
        result = extractor(query=query, segment=segment[:5000])
        excerpt = str(getattr(result, "evidence", "")).strip()
        if not excerpt:
            return None

        rationale = str(getattr(result, "rationale", "")).strip() or rationale_hint
        confidence = self._coerce_score(
            getattr(result, "confidence", ""),
            fallback=fallback_weight,
        )

        return EvidenceItem(
            asset_id=source_path,
            query=query,
            source_path=f"{source_path}#{node_suffix}",
            excerpt=excerpt[:800],
            rationale=rationale or "Recursive LM exploration selected this segment.",
            weight=max(confidence, fallback_weight),
        )

    def _split_text_for_rlm(self, text: str) -> list[str]:
        """Split large text into two coherent halves for recursive exploration."""
        midpoint = len(text) // 2
        split_at = text.rfind("\n", max(0, midpoint - 250), min(len(text), midpoint + 250))
        if split_at <= 0:
            split_at = text.rfind(" ", max(0, midpoint - 120), min(len(text), midpoint + 120))
        if split_at <= 0:
            split_at = midpoint

        left = text[:split_at].strip()
        right = text[split_at:].strip()
        parts = [part for part in (left, right) if part]
        return parts or [text]

    @staticmethod
    def _coerce_score(raw: Any, *, fallback: float) -> float:
        """Parse a model-produced 0-1 score while tolerating messy text output."""
        if isinstance(raw, (int, float)):
            return max(0.0, min(float(raw), 1.0))

        text = str(raw).strip()
        for token in text.replace("%", "").split():
            try:
                value = float(token.rstrip(".,;:"))
            except ValueError:
                continue
            if value > 1.0:
                value /= 100.0
            return max(0.0, min(value, 1.0))

        return max(0.0, min(fallback, 1.0))
