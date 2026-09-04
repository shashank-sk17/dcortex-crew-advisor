"""Exemplar corpus for intent routing.

The 38 gold prompts total 776 tokens, which is smaller than a single retrieval
round-trip. So they ship **inside the cached system prompt** and the router
sees all of them, rather than a top-3 approximation of them. That is strictly
more accurate than retrieval and needs no index (DECISIONS.md #15).

The cosine index here exists for the one corpus that will actually grow — the
decision audit log — and for `explain_rule` lookups. It is deliberately a
NumPy dot product: 38x384 floats is 58 KB, and an ANN index costs more to
build than the scan it replaces.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol, Sequence

import numpy as np

from agent import config
from agent.entities import mask


@dataclass(frozen=True, slots=True)
class Exemplar:
    question_id: str
    tier: int
    prompt: str
    masked: str
    rules_ref: tuple[str, ...] = ()


@lru_cache(maxsize=1)
def load_exemplars() -> tuple[Exemplar, ...]:
    """Read the 38 gold questions and mask their identifiers."""
    path = config.DATA_DIR / "questions.json"
    if not path.exists():  # keeps imports safe if the dataset is not vendored
        return ()

    raw = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        Exemplar(
            question_id=q["question_id"],
            tier=int(q["tier"]),
            prompt=q["prompt"],
            masked=mask(q["prompt"]),
            rules_ref=tuple(q.get("rules_ref") or ()),
        )
        for q in raw
    )


def exemplar_block(max_per_tier: int | None = None) -> str:
    """Render every exemplar as a cacheable system-prompt section.

    Masked form is used, not raw: the router is deciding *what kind of ask*
    this is, and concrete ids only add noise to that judgement.
    """
    rows = load_exemplars()
    if not rows:
        return ""

    lines: list[str] = []
    for tier in (1, 2, 3):
        in_tier = [e for e in rows if e.tier == tier]
        if max_per_tier:
            in_tier = in_tier[:max_per_tier]
        if not in_tier:
            continue
        lines.append(f"\n### Tier {tier}")
        lines += [f"- {e.masked}" for e in in_tier]
    return "\n".join(lines).strip()


# --------------------------------------------------------------------------
# Optional dense index — for the audit log, not for routing
# --------------------------------------------------------------------------


class Embedder(Protocol):
    """A real embedder (all-MiniLM-L6-v2, or pgvector's) satisfies this."""

    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


class HashingEmbedder:
    """Dependency-free stand-in for a sentence embedder.

    Character n-gram hashing into a fixed vector. It is *not* semantic — near
    synonyms will not match — but it is deterministic, needs no model download,
    and lets the retrieval path be exercised end to end. Replace with
    all-MiniLM-L6-v2 or pgvector when the audit log is real (issue #23).
    """

    def __init__(self, dim: int = config.EMBED_DIM, ngram: int = 4) -> None:
        self.dim = dim
        self.ngram = ngram

    def _one(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        s = text.lower()
        for i in range(max(len(s) - self.ngram + 1, 1)):
            gram = s[i : i + self.ngram]
            vec[hash(gram) % self.dim] += 1.0
        norm = np.linalg.norm(vec)
        return vec / norm if norm else vec

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        return np.vstack([self._one(t) for t in texts]) if texts else np.zeros((0, self.dim))


@dataclass(slots=True)
class Match:
    exemplar: Exemplar
    score: float


class ExemplarIndex:
    """Brute-force cosine over the masked corpus.

    No HNSW, no IVF, no FAISS: at n=38 the index build costs more than the
    scan. `search` returns nothing at all below the similarity floor — a
    misleading exemplar is worse than none, because it steers the planner
    confidently into the wrong toolchain.
    """

    def __init__(
        self,
        exemplars: Sequence[Exemplar] | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self.exemplars = tuple(exemplars if exemplars is not None else load_exemplars())
        self.embedder = embedder or HashingEmbedder()
        self._matrix = (
            self.embedder.encode([e.masked for e in self.exemplars])
            if self.exemplars
            else np.zeros((0, config.EMBED_DIM), dtype=np.float32)
        )

    def search(
        self,
        query: str,
        k: int = config.RETRIEVAL_K,
        min_similarity: float = config.RETRIEVAL_MIN_SIMILARITY,
        one_per_tier: bool = True,
    ) -> list[Match]:
        """Nearest exemplars to `query`, masked the same way the corpus was.

        `one_per_tier` returns contrast rather than three near-duplicates of
        the same tier, which is what actually helps a classifier.
        """
        if not len(self._matrix):
            return []

        q = self.embedder.encode([mask(query)])[0]
        scores = self._matrix @ q

        order = np.argsort(scores)[::-1]
        out: list[Match] = []
        seen_tiers: set[int] = set()

        for idx in order:
            score = float(scores[idx])
            if score < min_similarity:
                break
            ex = self.exemplars[idx]
            if one_per_tier and ex.tier in seen_tiers:
                continue
            seen_tiers.add(ex.tier)
            out.append(Match(ex, score))
            if len(out) >= k:
                break
        return out
