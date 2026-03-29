"""Stratified batch sampler for Driftcut."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from driftcut.config import SamplingConfig
from driftcut.corpus import Corpus, PromptRecord

# Criticality ordering for priority sampling: high-criticality first in early batches.
_CRITICALITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class Batch:
    batch_number: int
    prompts: list[PromptRecord] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.prompts)


class StratifiedSampler:
    """Produces stratified batches from a corpus.

    Each batch contains up to `batch_size_per_category` prompts per category.
    Early batches prioritize high-criticality prompts. No prompt is repeated
    across batches.
    """

    def __init__(
        self,
        corpus: Corpus,
        config: SamplingConfig,
        *,
        seed: int | None = None,
    ) -> None:
        self._config = config
        self._categories = corpus.categories

        # Build per-category pools sorted by criticality (high first),
        # with random shuffle within each criticality tier.
        rng = random.Random(seed)
        self._pools: dict[str, list[PromptRecord]] = {}
        for cat in self._categories:
            records = list(corpus.by_category(cat))
            rng.shuffle(records)
            records.sort(key=lambda r: _CRITICALITY_ORDER.get(r.criticality, 99))
            self._pools[cat] = records

        self._batch_number = 0

    @property
    def total_batches_possible(self) -> int:
        """Max batches before exhausting the smallest category, capped by max_batches."""
        if not self._categories:
            return 0
        per_cat = self._config.batch_size_per_category
        max_from_corpus = min(
            len(pool) // per_cat for pool in self._pools.values()
        )
        return min(max_from_corpus, self._config.max_batches)

    @property
    def total_prompts_planned(self) -> int:
        """Total prompts that will be tested across all planned batches."""
        per_batch = self._config.batch_size_per_category * len(self._categories)
        return self.total_batches_possible * per_batch

    def has_next(self) -> bool:
        if self._batch_number >= self._config.max_batches:
            return False
        per_cat = self._config.batch_size_per_category
        return all(len(pool) >= per_cat for pool in self._pools.values())

    def next_batch(self) -> Batch:
        """Draw the next stratified batch. Raises StopIteration if exhausted."""
        if not self.has_next():
            raise StopIteration("No more batches available")
        self._batch_number += 1
        per_cat = self._config.batch_size_per_category
        prompts: list[PromptRecord] = []
        for cat in self._categories:
            pool = self._pools[cat]
            selected = pool[:per_cat]
            self._pools[cat] = pool[per_cat:]
            prompts.extend(selected)
        return Batch(batch_number=self._batch_number, prompts=prompts)

    def __iter__(self):
        return self

    def __next__(self) -> Batch:
        if not self.has_next():
            raise StopIteration
        return self.next_batch()
