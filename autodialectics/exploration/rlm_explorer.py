"""Context exploration: load assets, dispatch to DSPy RLM or recursive fallback."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from autodialectics.schemas import AssetKind, EvidenceBundle, EvidenceItem
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
    ) -> None:
        self.use_dspy_rlm = use_dspy_rlm
        self.max_evidence_items = max_evidence_items
        self.rlm_threshold_chars = rlm_threshold_chars

    # ── Public API ────────────────────────────────────────────────────

    def explore(
        self,
        contract: TaskContract,
        queries: list[str] | None = None,
    ) -> EvidenceBundle:
        """Load assets and explore them to build an evidence bundle."""
        queries = queries or ["What is the main task and context?"]
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
                    items.extend(result)
                    generated_with_rlm = True
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

            for item in items:
                for q in queries:
                    if item.query == q:
                        coverage_map.setdefault(q, []).append(
                            item.evidence_id
                        )

        # Deduplicate and limit
        seen: set[str] = set()
        unique_items: list[EvidenceItem] = []
        for item in items:
            if item.evidence_id not in seen:
                seen.add(item.evidence_id)
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
        """Use DSPy RLM for retrieval-augmented exploration."""
        import dspy  # type: ignore[import-untyped]

        class EvidenceRetrieval(dspy.Signature):  # type: ignore[misc]
            """Retrieve evidence passages relevant to a query."""

            context: str = dspy.InputField(desc="Asset content chunks")
            query: str = dspy.InputField(desc="Exploration query")
            evidence: str = dspy.OutputField(
                desc="Relevant evidence excerpt"
            )
            rationale: str = dspy.OutputField(
                desc="Why this excerpt is relevant"
            )

        class EvidenceRetriever(dspy.Module):  # type: ignore[misc]
            def __init__(self) -> None:  # type: ignore[override]
                super().__init__()
                self.retrieve = dspy.ChainOfThought(EvidenceRetrieval)

            def forward(self, context: str, query: str):  # type: ignore[override]
                return self.retrieve(context=context, query=query)

        items: list[EvidenceItem] = []
        for source_path, text in loaded:
            chunks = chunk_text(text)
            for idx, chunk in enumerate(chunks):
                try:
                    retriever = EvidenceRetriever()
                    result = retriever(context=chunk, query=query)
                    items.append(
                        EvidenceItem(
                            asset_id=source_path,
                            query=query,
                            source_path=f"{source_path}#chunk_{idx}",
                            excerpt=str(result.evidence)[:800],
                            rationale=str(result.rationale),
                            weight=0.7,
                        )
                    )
                except Exception as exc:
                    logger.debug(
                        "RLM chunk %s#%d failed: %s", source_path, idx, exc
                    )

        items.sort(key=lambda x: x.weight, reverse=True)
        return items[: self.max_evidence_items]
