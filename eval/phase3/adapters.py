#!/usr/bin/env python3
"""Phase 3 Generator Adapters.

Provides a unified interface for answer generation:
- A0: Real production extractive generator (EvidenceExtractiveGenerator)
- A2 (Mock / Test Fixture): Simulated span-selection LLM
- A3 (Mock / Test Fixture): Simulated paraphrasing LLM

The interface allows future addition of real LLM clients (Claude Haiku, Claude Sonnet, Ollama)
without modifying the benchmark harness or evaluation metrics.
"""
from __future__ import annotations

import copy
import re
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import rag_context as RC
import rag_evidence as RE
import rag_generate as RG
import rag_text as T


@dataclass
class AdapterResult:
    """Standardized output from any generator adapter."""
    adapter_id: str
    text: str
    raw_text: str
    refused: bool
    latency_ms: float
    evidence: Optional[Dict[str, Any]] = None
    telemetry: Dict[str, Any] = field(default_factory=dict)
    is_test_fixture: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "text": self.text,
            "refused": self.refused,
            "latency_ms": round(self.latency_ms, 2),
            "telemetry": self.telemetry,
            "is_test_fixture": self.is_test_fixture,
        }


class GeneratorAdapter(ABC):
    """Abstract base class for all generator adapters."""

    def __init__(self, adapter_id: str, is_test_fixture: bool = False) -> None:
        self.adapter_id = adapter_id
        self.is_test_fixture = is_test_fixture

    @abstractmethod
    def generate(self, question: str, context: RC.ContextBlock, snapshot: Optional[Dict[str, Any]] = None) -> AdapterResult:
        """Generate an answer given a question and a context block."""
        pass


class A0ExtractiveAdapter(GeneratorAdapter):
    """Adapter A0: Production extractive generator baseline.

    Uses the real shipped EvidenceExtractiveGenerator with SHIPPED_TAU (0.5).
    Deterministic, verbatim source spans, citation-aware, with procedural limitation detection.
    """

    def __init__(self, tau: float = RE.SHIPPED_TAU) -> None:
        super().__init__(adapter_id="A0", is_test_fixture=False)
        self.generator = RE.EvidenceExtractiveGenerator(tau=tau)

    def generate(self, question: str, context: RC.ContextBlock, snapshot: Optional[Dict[str, Any]] = None) -> AdapterResult:
        if hasattr(self.generator, "reset_request_state"):
            self.generator.reset_request_state()

        t0 = time.perf_counter()
        gen_res = self.generator.generate(question, context)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        telemetry = {
            "token_in": None,
            "token_out": None,
            "cost_per_1k": None,
            "generator_name": self.generator.name,
        }

        return AdapterResult(
            adapter_id="A0",
            text=gen_res.text,
            raw_text=gen_res.raw_text,
            refused=gen_res.refused,
            latency_ms=latency_ms,
            evidence=copy.deepcopy(gen_res.evidence) if gen_res.evidence else None,
            telemetry=telemetry,
            is_test_fixture=False,
        )


class A2SpanSelectorMockAdapter(GeneratorAdapter):
    """Adapter A2 (TEST FIXTURE): Simulated span-selection LLM.

    NOTE: This is a test fixture mock for validating the harness plumbing.
    It does NOT call a real model. Its results must never be cited as real LLM performance.
    """

    def __init__(self) -> None:
        super().__init__(adapter_id="A2_mock", is_test_fixture=True)

    def generate(self, question: str, context: RC.ContextBlock, snapshot: Optional[Dict[str, Any]] = None) -> AdapterResult:
        t0 = time.perf_counter()

        # Mock span selector selects up to 2 high-scoring sentences from context items
        lines: List[str] = []
        for item in context.items:
            sentences = T.split_sentences(item.rendered_text)
            if sentences:
                lines.append(f"{sentences[0]} [{item.marker}]")
            if len(lines) >= 2:
                break

        text = "\n".join(lines) if lines else RG.NO_ANSWER_TEXT
        latency_ms = (time.perf_counter() - t0) * 1000.0

        telemetry = {
            "disclaimer": "TEST_FIXTURE_MOCK: NOT A REAL LLM RUN",
            "token_in": None,
            "token_out": None,
            "cost_per_1k": None,
        }

        return AdapterResult(
            adapter_id="A2_mock",
            text=text,
            raw_text=text,
            refused=not bool(lines),
            latency_ms=latency_ms,
            telemetry=telemetry,
            is_test_fixture=True,
        )


class A3ParaphraserMockAdapter(GeneratorAdapter):
    """Adapter A3 (TEST FIXTURE): Simulated paraphrasing LLM.

    NOTE: This is a test fixture mock for validating the harness plumbing.
    It does NOT call a real model. Its results must never be cited as real LLM performance.
    """

    def __init__(self) -> None:
        super().__init__(adapter_id="A3_mock", is_test_fixture=True)

    def generate(self, question: str, context: RC.ContextBlock, snapshot: Optional[Dict[str, Any]] = None) -> AdapterResult:
        t0 = time.perf_counter()

        # Mock paraphraser creates a summary style response with citations
        lines: List[str] = []
        for item in context.items:
            sentences = T.split_sentences(item.rendered_text)
            if sentences:
                # Slight paraphrase simulation
                paraphrased = f"According to SAP documentation, {sentences[0].lower()}"
                lines.append(f"{paraphrased} [{item.marker}]")
            if len(lines) >= 2:
                break

        text = " ".join(lines) if lines else RG.NO_ANSWER_TEXT
        latency_ms = (time.perf_counter() - t0) * 1000.0

        telemetry = {
            "disclaimer": "TEST_FIXTURE_MOCK: NOT A REAL LLM RUN",
            "semantic_eval_required": True,
            "token_in": None,
            "token_out": None,
            "cost_per_1k": None,
        }

        return AdapterResult(
            adapter_id="A3_mock",
            text=text,
            raw_text=text,
            refused=not bool(lines),
            latency_ms=latency_ms,
            telemetry=telemetry,
            is_test_fixture=True,
        )


def build_context_block(context_items: Sequence[Mapping[str, Any]]) -> RC.ContextBlock:
    """Helper to convert cached snapshot items into a rag_context.ContextBlock."""
    items: List[RC.ContextItem] = []
    for i, item in enumerate(context_items, start=1):
        txt = item.get("text") or ""
        rendered = item.get("rendered_text") or txt
        items.append(RC.ContextItem(
            marker=item.get("marker") or f"S{i}",
            chunk_id=item.get("chunk_id") or f"chunk_{i}",
            guide_id=item.get("guide_id") or "guide_eval",
            page_id=item.get("page_id") or "page_eval",
            title=item.get("title") or "",
            heading_path=list(item.get("heading_path") or ()),
            section_title=(item.get("heading_path") or [""])[-1] if item.get("heading_path") else "",
            chunk_index=i,
            rank=i,
            similarity=1.0,
            text=txt,
            rendered_text=rendered,
            tokens=len(rendered.split()),
            content_hash=f"hash_{i}",
            source_url=item.get("url") or "",
        ))
    return RC.ContextBlock(items=items)


def get_adapter(adapter_id: str) -> GeneratorAdapter:
    """Factory to retrieve generator adapters by ID."""
    aid = adapter_id.upper()
    if aid in ("A0", "A0_EXTRACTIVE", "EXTRACTIVE"):
        return A0ExtractiveAdapter()
    elif aid in ("A2", "A2_MOCK", "MOCK_A2"):
        return A2SpanSelectorMockAdapter()
    elif aid in ("A3", "A3_MOCK", "MOCK_A3"):
        return A3ParaphraserMockAdapter()
    else:
        raise ValueError(f"Unknown or unsupported adapter '{adapter_id}'. For offline Phase 3, choose 'A0', 'A2_mock', or 'A3_mock'.")
