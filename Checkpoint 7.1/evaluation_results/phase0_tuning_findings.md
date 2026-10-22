# Checkpoint 7.1 performance tuning: Phase 0 findings (offline, no API calls)

Measured on 2026-10-20 before any tuning code was written, to decide which planned
optimisations are worth building and how. The scripts ran against the table-rendered chunk
index (141,126 chunks) used by the v2 and hardened agents.

## 1. Start-up: where the time goes (one process start)

| Stage | Time |
|---|---|
| Import the 4.1 / 5.1 modules (LangChain, Chroma, NetworkX) | 9.5 s |
| Load the chunk cache (`chunks.jsonl`, 250 MB JSON) | 14.2 s |
| Tokenize 141k chunks for BM25 | 10.8 s |
| Build `rank_bm25.BM25Okapi` | 10.1 s |
| Build the NetworkX graph | 1.7 s |

**Implications:**
- **BM25 is worth saving to disk.** Tokenizing and building it costs 21 s on every start.
- **The graph is not:** it builds in 1.7 s.
- **The chunk-cache JSON** (14 s) is the next target if start-up matters later.

## 2. BM25 per query: the bigger win

Timed over the 43 distinct passage-search queries the hardened agent ran in its two golden-suite
runs:

| Implementation | Per search, p50 / max | Rankings vs `rank_bm25` | Build | Save / load | On disk |
|---|---|---|---|---|---|
| `rank_bm25.BM25Okapi` (current) | **853 ms / 4.0 s** | (reference) | 21 s per start | none (rebuilt) | – |
| `bm25s`, method `robertson` | 1.5 ms / 10 ms | top-8 overlap 81%, worst query 25% | 35 s | 0.3 s / 0.3 s | 106 MB |
| `bm25s`, best variant (`lucene`, `atire`, `bm25+`) | ~1.5 ms | top-8 87%, top-40 87%, worst 25–38% | ~35 s | 0.3 s | ~106 MB |
| **Exact BM25Okapi on a SciPy sparse matrix** | **1.9 ms / 15 ms** | **identical: max score difference 4 × 10⁻¹⁰; top-40 identical on 43/43** | 24 s once | 0.5 s / **0.7 s** | 153 MB |

- **Why the current version is slow.** `rank_bm25` loops over all 141k documents in Python for
  each query term. The same formula on a precomputed sparse weight matrix (IDF with the same
  epsilon floor, `k1=1.5`, `b=0.75`) needs only one column lookup per term.
- **The size of the saving.** Each BM25 call drops from ~0.85 s to ~2 ms, and an agent query
  makes several: the seed search, each `chunks` step, and the full-score lookups used by the
  graph and section tools.
- **Recommendation: the exact sparse scorer, not `bm25s`.** It's as fast, it **leaves rankings
  unchanged** (so retrieval quality needn't be re-checked), and it needs no new dependency (NumPy
  and SciPy are already installed). It saves with `scipy.sparse.save_npz` plus a JSON vocabulary,
  so loading runs no pickled code.

## 3. Verify-and-repair: how many planner retries are near-miss quotes?

Analysed from every `VERIFY` entry in the 5.1 and 7.1 agent logs (116 planner retries). Each
failed quote was fuzzy-matched against the cited article's full text, which gives an upper
bound, since the agent sees only the retrieved passages.

| | Count |
|---|---|
| Retries with **no failed quote** (only a clue with no fact), so repair can't help | 54 of 116 |
| Failed quotes: near miss, similarity ≥ 0.90, so **repairable** | 45 of 103 |
| Failed quotes: borderline, 0.80–0.90 | 5 |
| Failed quotes: paraphrase, < 0.80, which should still go back to the planner | 49 |
| Failed quotes: wrong or missing source file | 4 |
| **Retries repair would avoid** (every failed quote repairable, and the repairs cover every uncovered clue) | **≤ 26 of 116 (22%)** |

**Implication:** a modest saving, about 0.04–0.07 planner calls per question (retries run at
0.18–0.32 per question). It's still worth doing, because it's cheap, deterministic and easy to
test. Repair should be limited to the cited file's passages in the context, with a high
threshold (~0.90).

## 4. Fast-path predicate: calibration on the golden suite

Candidate rule: no multi-hop markers in the question ("both", "before/after", "compare", "the
university where…", "same year"…), **and** at least half of the 8 seed hits come from one
article **and** that article's title words appear in the question. Checked against how often the
hardened agent answered each golden question correctly straight from the seed (2 runs):

- **Flagged as fast-path:** G15 (Sarajevo vs Dunedin population: seed-only and correct 2/2) and
  Q019 (La La Land: 1/2). That's 2 of 17.
- **Correctly kept on the full path:** G08, G13, G16, Q009, Q049 and the other multi-hop
  questions, none of which are ever answered from the seed.
- **Answered from the seed but not flagged** (they stay on the full path, which is safe): G06,
  G07 and Q072, whose seeds are spread across several articles.

**Implication:** the golden suite (built to be hard) will show little fast-path benefit, and 17
questions are too few to set thresholds without overfitting. A **simple one-hop set** is needed.
The 3.1 `golden_suite.json` has 24 answerable, single-document fact-lookup questions in the
same schema (e.g. *"Which film won Best Picture at the 68th Academy Awards?"*, *"Who was offered
the Hyman Roth role and turned it down?"*). These would be used to tune the predicate, with the
golden suite as the check against quality regressions.

## 5. What this changes in the plan

| Planned item | Phase 0 verdict |
|---|---|
| BM25 to disk + `bm25s` | **Change: exact sparse BM25Okapi instead.** ~450× faster per search, identical rankings, loads in 0.7 s, no new dependency |
| Graph to disk | **Drop:** it builds in 1.7 s |
| Verify-and-repair | Keep: saves ≤ 22% of retries; cheap and deterministic |
| Fast path (seed → answer) | Keep, with the deterministic predicate above; tune on the 24-question simple set |
| Conditional clue step, selective reasoning, LFU cache | Unchanged (Phases 2–3) |

Scripts: `phase0_bm25.py`, `phase0_bm25_variants.py`, `phase0_sparse_okapi.py`,
`phase0_repair.py` and `phase0_fastpath.py`, run from the session scratchpad. They will be
folded into the tuned module's self-check and benchmark commands.
