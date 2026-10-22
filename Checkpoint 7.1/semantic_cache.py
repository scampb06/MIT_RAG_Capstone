r"""Semantic answer cache with least-frequently-used eviction and aging (Checkpoint 7.1).

Adapted from Lab 7.2's semantic cache (Module 7/lab_7_2_efficient_agent_solution.py):
a question is embedded, compared by cosine similarity with the cached questions, and
the cached answer is returned only above a high threshold, because a wrong cached
answer is worse than recomputing one. Differences from the lab:

| | Lab 7.2 | This cache |
|---|---|---|
| Eviction when full | oldest entry first | least frequently used, with aging; ties go to the least recently used; new entries get a short grace period |
| Near-miss guard | similarity threshold only | the matched question must contain exactly the same numbers ("1992 vote" never matches "1994 vote") |
| Stale answers | none | entries are keyed by the agent configuration (models, prompts, features), so a change invalidates them |
| Context-dependent questions | a small-model check on every hit | questions that rely on pronouns are not cached; in a chat, the caller also skips follow-ups ("And…", "What about…", under 4 words) |
| Storage | Chroma collection | NumPy in memory, JSON on disk (no pickled code on load) |

Why LFU with aging, not plain LFU: plain LFU evicts every new entry first (it has one
hit), so a newly popular question can never stay in, and old favourites stay for ever.
Hit counts here decay by half every `half_life` lookups, and entries younger than
`grace` lookups are only evicted if every entry is that young.

Time is counted in lookups, not seconds, so eviction is deterministic and testable.

    python semantic_cache.py --self-check     offline unit tests (fake embeddings)
    python semantic_cache.py --simulate       offline eviction-policy comparison
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

POLICIES = ("lfu_aging", "lfu", "lru", "fifo")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_PRONOUN = re.compile(r"\b(he|she|they|him|her|them|his|hers|their|it|its|this|that|these|those)\b", re.IGNORECASE)
_NAME = re.compile(r"\b[A-Z][a-z]+|\b[A-Z]{2,}|\d")


def numbers_in(text: str) -> tuple[str, ...]:
    return tuple(sorted(_NUMBER.findall(text)))


def self_contained(question: str) -> bool:
    """False for questions that lean on pronouns with no name or number to anchor them
    ("When was he born?"): their answer depends on context the cache cannot see."""
    words = question.split()
    named = any(_NAME.match(word) for word in words[1:]) or bool(_NAME.match(words[0][1:] if words else ""))
    return named or not _PRONOUN.search(question)


@dataclass
class CacheEntry:
    question: str
    answer: str
    embedding: np.ndarray
    config: str
    numbers: tuple[str, ...]
    created: int            # clock at store time
    last_used: int          # clock at the last hit (or store)
    score: float = 1.0      # decayed hit count
    scored_at: int = 0      # clock when score was last updated
    hits: int = 0           # lifetime hits, for statistics


class SemanticCache:
    def __init__(self, embed: Callable[[str], list[float]], path: Path | None = None, max_size: int = 400,
                 threshold: float = 0.934, policy: str = "lfu_aging", half_life: int = 200, grace: int = 20):
        if policy not in POLICIES:
            raise ValueError(f"policy must be one of {POLICIES}")
        self.embed, self.path = embed, path
        self.max_size, self.threshold, self.policy = max_size, threshold, policy
        self.half_life, self.grace = half_life, grace
        self.entries: list[CacheEntry] = []
        self.clock = 0
        self.counters = {"lookups": 0, "hits": 0, "misses": 0, "blocked_by_number_guard": 0,
                         "stores": 0, "evictions": 0, "skipped_not_self_contained": 0}
        if path is not None and path.is_file():
            self._load()

    # -------------------------------------------------------------- lookups
    def lookup(self, question: str, config: str, embedding: np.ndarray | None = None) -> dict[str, Any] | None:
        """The cached answer for a close-enough question, or None. Every call advances the clock."""
        self.clock += 1
        self.counters["lookups"] += 1
        if not self_contained(question):
            self.counters["skipped_not_self_contained"] += 1
            self.counters["misses"] += 1
            return None
        candidates = [entry for entry in self.entries if entry.config == config]
        if not candidates:
            self.counters["misses"] += 1
            return None
        vector = self._unit(embedding if embedding is not None else self.embed(question))
        similarities = np.array([float(entry.embedding @ vector) for entry in candidates])
        best = int(np.argmax(similarities))
        entry, similarity = candidates[best], float(similarities[best])
        if similarity < self.threshold:
            self.counters["misses"] += 1
            return None
        if entry.numbers != numbers_in(question):
            self.counters["blocked_by_number_guard"] += 1
            self.counters["misses"] += 1
            return None
        entry.score = self._decayed(entry) + 1.0
        entry.scored_at = entry.last_used = self.clock
        entry.hits += 1
        self.counters["hits"] += 1
        return {"answer": entry.answer, "similarity": round(similarity, 4), "cached_question": entry.question}

    def store(self, question: str, answer: str, config: str, embedding: np.ndarray | None = None) -> bool:
        if not self_contained(question):
            self.counters["skipped_not_self_contained"] += 1
            return False
        vector = self._unit(embedding if embedding is not None else self.embed(question))
        for entry in self.entries:       # the same question again replaces the old answer
            if entry.config == config and entry.question == question:
                entry.answer, entry.embedding = answer, vector
                return True
        while len(self.entries) >= self.max_size:
            self._evict()
        self.entries.append(CacheEntry(question, answer, vector, config, numbers_in(question),
                                       created=self.clock, last_used=self.clock, scored_at=self.clock))
        self.counters["stores"] += 1
        if self.path is not None:
            self.save()
        return True

    # ------------------------------------------------------------- eviction
    def _decayed(self, entry: CacheEntry) -> float:
        if self.policy != "lfu_aging":
            return entry.score
        return entry.score * math.pow(0.5, (self.clock - entry.scored_at) / self.half_life)

    def _evict(self) -> CacheEntry:
        pool = self.entries
        if self.policy in ("lfu_aging", "lfu"):
            settled = [entry for entry in pool if self.clock - entry.created >= self.grace]
            pool = settled or pool                      # grace period, unless every entry is new
            victim = min(pool, key=lambda entry: (self._decayed(entry), entry.last_used, entry.created))
        elif self.policy == "lru":
            victim = min(pool, key=lambda entry: (entry.last_used, entry.created))
        else:                                          # fifo, Lab 7.2's oldest-first
            victim = min(pool, key=lambda entry: entry.created)
        self.entries.remove(victim)
        self.counters["evictions"] += 1
        return victim

    # ---------------------------------------------------------- statistics
    def stats(self) -> dict[str, Any]:
        lookups = self.counters["lookups"]
        return {**self.counters, "size": len(self.entries), "max_size": self.max_size, "policy": self.policy,
                "threshold": self.threshold, "hit_rate": round(self.counters["hits"] / lookups, 3) if lookups else None,
                "top_entries": [{"question": e.question[:80], "hits": e.hits, "score": round(self._decayed(e), 3)}
                                for e in sorted(self.entries, key=lambda e: -self._decayed(e))[:5]]}

    # ---------------------------------------------------------- persistence
    @staticmethod
    def _unit(vector: Any) -> np.ndarray:
        array = np.asarray(vector, dtype=np.float64)
        norm = np.linalg.norm(array)
        return array / norm if norm else array

    def save(self) -> None:
        """Write entries, clock and counters. Called after every store; call it at the end of a
        session too, so the hits and clock since the last store are kept."""
        if self.path is None:
            return
        data = {"format": 1, "clock": self.clock, "counters": self.counters, "entries": [
            {"question": e.question, "answer": e.answer, "embedding": e.embedding.round(6).tolist(), "config": e.config,
             "created": e.created, "last_used": e.last_used, "score": e.score, "scored_at": e.scored_at, "hits": e.hits}
            for e in self.entries]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")     # write, then swap: never a half-written file
        temporary.write_text(json.dumps(data), encoding="utf-8")
        os.replace(temporary, self.path)

    def _load(self) -> None:
        """Load a saved cache. A damaged file is set aside and the cache starts empty: a lost
        cache costs only misses, while refusing to start would stop the agent."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            damaged = self.path.with_name(self.path.name + ".damaged")
            os.replace(self.path, damaged)
            print(f"Cache file unreadable ({error.__class__.__name__}); moved to {damaged}, starting empty")
            return
        self.clock, self.counters = data["clock"], {**self.counters, **data["counters"]}
        self.entries = [CacheEntry(e["question"], e["answer"], self._unit(e["embedding"]), e["config"],
                                   numbers_in(e["question"]), e["created"], e["last_used"], e["score"],
                                   e["scored_at"], e["hits"]) for e in data["entries"]]


# %% [markdown]
# ## Offline tests and simulation

# %%
def _fake_embedder(dimension: int = 64, seed: int = 7) -> Callable[[str], np.ndarray]:
    """Deterministic fake embeddings: a question 'topic:N|variant:M' maps to its topic's
    vector plus a small variant-specific perturbation (paraphrases are close, topics far)."""
    rng = np.random.default_rng(seed)
    topics: dict[str, np.ndarray] = {}

    def embed(text: str) -> np.ndarray:
        topic, _, variant = text.partition("|")
        if topic not in topics:
            topics[topic] = rng.normal(size=dimension)
        noise = np.random.default_rng(zlib.crc32(text.encode())).normal(size=dimension) * 0.15 * bool(variant)
        return topics[topic] + noise
    return embed


def self_check() -> None:
    failures: list[str] = []

    def check(condition: bool, message: str) -> None:
        print(("  ok    " if condition else "  FAIL  ") + message)
        if not condition:
            failures.append(message)

    embed = _fake_embedder()
    cache = SemanticCache(embed, max_size=3, threshold=0.90, grace=0)
    cache.store("Who wrote Nineteen Eighty-Four", "Orwell", "cfg")
    check(cache.lookup("Who wrote Nineteen Eighty-Four|paraphrase", "cfg") is not None, "a paraphrase hits")
    check(cache.lookup("Who directed King Kong", "cfg") is None, "a different question misses")
    check(cache.lookup("Who wrote Nineteen Eighty-Four", "other-config") is None, "another configuration never hits")
    cache.store("Best Picture at the 68th ceremony", "Braveheart", "cfg")
    check(cache.lookup("Best Picture at the 68th ceremony|paraphrase", "cfg") is not None, "same numbers: hit")
    hit = cache.lookup("Best Picture at the 68th ceremony|x 89", "cfg")
    check(hit is None and cache.counters["blocked_by_number_guard"] == 1, "different numbers: blocked by the guard")
    check(not self_contained("When was he born?") and self_contained("When was Orwell born?")
          and self_contained("What is the highest-grossing film of all time?"), "pronoun-only questions are not cached")

    # LFU with aging: the frequently used entry survives; ties go to the least recently used.
    cache = SemanticCache(embed, max_size=3, threshold=0.90, policy="lfu_aging", half_life=1000, grace=0)
    for name in ("A", "B", "C"):
        cache.store(f"topic {name}", name, "cfg")
    for _ in range(3):
        cache.lookup("topic A", "cfg")
    cache.lookup("topic C", "cfg")
    cache.store("topic D", "D", "cfg")
    check({e.question for e in cache.entries} == {"topic A", "topic C", "topic D"}, "lfu_aging: the least used (B) is evicted")
    fifo = SemanticCache(embed, max_size=3, threshold=0.90, policy="fifo")
    for name in ("A", "B", "C"):
        fifo.store(f"topic {name}", name, "cfg")
    for _ in range(3):
        fifo.lookup("topic A", "cfg")
    fifo.store("topic D", "D", "cfg")
    check({e.question for e in fifo.entries} == {"topic B", "topic C", "topic D"}, "fifo (Lab 7.2): the oldest (A) is evicted despite its hits")

    # Aging: a once-popular entry fades, so a newly popular one is kept instead.
    aged = SemanticCache(embed, max_size=2, threshold=0.90, policy="lfu_aging", half_life=10, grace=0)
    aged.store("topic old", "old", "cfg")
    for _ in range(5):
        aged.lookup("topic old", "cfg")
    aged.store("topic new", "new", "cfg")
    for _ in range(60):
        aged.lookup("topic new", "cfg")
    aged.store("topic newest", "x", "cfg")
    check({e.question for e in aged.entries} == {"topic new", "topic newest"}, "aging: the faded favourite is evicted")
    plain = SemanticCache(embed, max_size=2, threshold=0.90, policy="lfu", grace=0)
    plain.store("topic old", "old", "cfg")
    for _ in range(5):
        plain.lookup("topic old", "cfg")
    plain.store("topic new", "new", "cfg")
    plain.store("topic newest", "x", "cfg")
    check({e.question for e in plain.entries} == {"topic old", "topic newest"}, "plain LFU: the new entry is evicted at once")

    grace = SemanticCache(embed, max_size=2, threshold=0.90, policy="lfu_aging", grace=5)
    grace.store("topic A", "A", "cfg")
    for _ in range(6):
        grace.lookup("topic A", "cfg")
    grace.store("topic B", "B", "cfg")
    grace.store("topic C", "C", "cfg")
    check({e.question for e in grace.entries} == {"topic B", "topic C"} or {e.question for e in grace.entries} == {"topic A", "topic C"},
          "grace: a just-stored entry is not the automatic victim")
    check(grace.counters["evictions"] == 1, "one eviction when full")

    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "cache.json"
        persisted = SemanticCache(embed, path=path, max_size=5)
        persisted.store("Who wrote Nineteen Eighty-Four", "Orwell", "cfg")
        persisted.lookup("Who wrote Nineteen Eighty-Four", "cfg")
        persisted.save()
        reloaded = SemanticCache(embed, path=path, max_size=5)
        check(len(reloaded.entries) == 1 and reloaded.clock == persisted.clock
              and reloaded.lookup("Who wrote Nineteen Eighty-Four|again", "cfg") is not None, "save and reload")
        check(not path.with_name("cache.json.tmp").exists(), "save leaves no temporary file")
        path.write_text('{"format": 1, "entries": [', encoding="utf-8")       # a half-written file
        damaged = SemanticCache(embed, path=path, max_size=5)
        check(not damaged.entries and path.with_name("cache.json.damaged").exists(),
              "a damaged cache file is set aside and the cache starts empty")
    print(f"\n{'All checks passed.' if not failures else f'{len(failures)} check(s) FAILED.'}")
    if failures:
        raise SystemExit(1)


def simulate(requests: int = 20000, topics: int = 600, seed: int = 11) -> list[dict[str, Any]]:
    """Offline eviction-policy comparison. Requests draw a topic from a Zipf-like
    distribution and a random paraphrase of it; halfway through, popularity shifts to
    other topics (a news event), which is where aging matters. Hit rate per policy and
    cache size; no model calls, fake embeddings."""
    rng = np.random.default_rng(seed)
    ranks = np.arange(1, topics + 1)
    weights = 1 / ranks ** 1.0
    weights /= weights.sum()
    first = rng.permutation(topics)
    second = np.concatenate([first[topics // 2:], first[:topics // 2]])   # new favourites after the shift
    workload = []
    for index in range(requests):
        order = first if index < requests // 2 else second
        topic = int(order[rng.choice(topics, p=weights)])
        workload.append(f"topic {topic}|v{rng.integers(0, 4)}")
    results = []
    for size in (25, 50, 100, 200):
        for policy in POLICIES:
            embed = _fake_embedder(seed=seed)
            cache = SemanticCache(embed, max_size=size, threshold=0.90, policy=policy, half_life=500, grace=10)
            vectors: dict[str, np.ndarray] = {}
            for question in workload:
                vector = vectors.setdefault(question, embed(question))
                if cache.lookup(question, "cfg", embedding=vector) is None:
                    cache.store(question, "answer", "cfg", embedding=vector)
            results.append({"cache_size": size, "policy": policy, "hit_rate": cache.stats()["hit_rate"]})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Semantic answer cache (Checkpoint 7.1).")
    parser.add_argument("--self-check", action="store_true", help="offline unit tests")
    parser.add_argument("--simulate", action="store_true", help="offline eviction-policy comparison")
    args = parser.parse_args()
    if args.self_check:
        self_check()
    if args.simulate:
        rows = simulate()
        sizes = sorted({row["cache_size"] for row in rows})
        print("| Cache size | " + " | ".join(POLICIES) + " |\n|---|" + "---|" * len(POLICIES))
        for size in sizes:
            rates = {row["policy"]: row["hit_rate"] for row in rows if row["cache_size"] == size}
            print(f"| {size} | " + " | ".join(f"{rates[p]:.1%}" for p in POLICIES) + " |")


if __name__ == "__main__":
    main()
