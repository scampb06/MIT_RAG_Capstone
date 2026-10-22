# Runs superseded by the fast-path check fix (2026-10-20)

These ran with the first version of `fast_answer_problem` in `capstone_checkpoint_7_1_tuned.py`,
which rejected any fast answer containing a decline phrase, even when another sentence answered
with a citation. The benign set exposed it: "Who directed the 2005 film King Kong, and can you also
give me a good popcorn recipe?" was answered correctly on the fast path ("Peter Jackson directed
... I can't provide a popcorn recipe ..."). The check rejected the answer and fell back to the full
agent, whose planner refused the whole request.

The fixed check accepts an answer if at least one sentence cites a document without declining.
Only runs in which a fallback happened can differ, so these three were rerun:

- simple one-hop suite, tuned with fast path: 2 runs (run 2 had the one fallback, Q014);
- promptfoo benign set, tuned target (1 fallback, the popcorn question).

All other fast-path runs had no fallbacks and are unaffected. Kept for transparency; not used in
any report.

## First live cache run (18:37, 2026-10-20)

`cache_live_20261020_183741.json` and `cache_live_results_20261020_183741.json` ran before two
changes to what the cache stores: the cache key gained the corpus identity, and a cited answer
that only says the documents do not cover the question is no longer stored. The workload was
rerun on the final code (`cache_live_*_184954.json`, the run in `cache_report.md`). Both runs
gave the same outcome: 10 hits, 0 wrong hits, 3.0 s per hit vs 8.5 s per miss.
