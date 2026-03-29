"""Tests for the stratified batch sampler."""

from pathlib import Path

from driftcut.config import SamplingConfig
from driftcut.corpus import load_corpus
from driftcut.sampler import StratifiedSampler

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def _make_sampler(
    batch_size: int = 2,
    max_batches: int = 5,
    min_batches: int = 2,
    seed: int = 42,
) -> StratifiedSampler:
    corpus = load_corpus(EXAMPLES_DIR / "prompts.csv")
    config = SamplingConfig(
        batch_size_per_category=batch_size,
        max_batches=max_batches,
        min_batches=min_batches,
    )
    return StratifiedSampler(corpus, config, seed=seed)


def test_batch_has_correct_size():
    sampler = _make_sampler(batch_size=2)
    batch = sampler.next_batch()
    # 4 categories × 2 per category = 8
    assert batch.size == 8


def test_batch_covers_all_categories():
    corpus = load_corpus(EXAMPLES_DIR / "prompts.csv")
    sampler = _make_sampler(batch_size=2)
    batch = sampler.next_batch()
    cats_in_batch = {p.category for p in batch.prompts}
    assert cats_in_batch == set(corpus.categories)


def test_no_repeats_across_batches():
    sampler = _make_sampler(batch_size=2)
    all_ids: list[str] = []
    for batch in sampler:
        all_ids.extend(p.id for p in batch.prompts)
    assert len(all_ids) == len(set(all_ids))


def test_total_batches_capped_by_max():
    sampler = _make_sampler(batch_size=2, max_batches=3)
    assert sampler.total_batches_possible == 3
    batches = list(sampler)
    assert len(batches) == 3


def test_total_batches_capped_by_corpus():
    # Smallest category (summarization) has 6 prompts. batch_size=2 → max 3 batches from corpus.
    sampler = _make_sampler(batch_size=2, max_batches=10)
    assert sampler.total_batches_possible == 3


def test_high_criticality_first_in_early_batches():
    sampler = _make_sampler(batch_size=2)
    batch1 = sampler.next_batch()
    high_count = sum(1 for p in batch1.prompts if p.criticality == "high")
    # With high-criticality prioritization, early batches should have more high-crit prompts
    # than a random sample would
    assert high_count > 0


def test_batch_numbering():
    sampler = _make_sampler(batch_size=2, max_batches=3)
    batches = list(sampler)
    assert [b.batch_number for b in batches] == [1, 2, 3]


def test_total_prompts_planned():
    sampler = _make_sampler(batch_size=2, max_batches=3)
    # 3 batches × 2 per category × 4 categories = 24
    assert sampler.total_prompts_planned == 24


def test_has_next_false_when_exhausted():
    sampler = _make_sampler(batch_size=2, max_batches=10)
    while sampler.has_next():
        sampler.next_batch()
    assert not sampler.has_next()
