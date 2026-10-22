r"""Checkpoint 7.1 performance tuning: before/after tables from saved runs (no API calls).

Compares evaluation runs by their run label (configuration.run_label in each results
file): the hardened agent as the baseline, then each tuned configuration. Writes
evaluation_results/tuning_before_after.md.

    python tuning_report.py
"""
from __future__ import annotations

import json
import statistics as st
from collections import defaultdict
from pathlib import Path

RESULTS = Path(__file__).with_name("evaluation_results")
HAIKU = "-planner-claude-haiku-4.5-answer-claude-haiku-4.5"
TUNED = "-tuned-sparse_bm25+repair"
# (heading, suite file, [(label shown, run_label in the results files)]); missing runs are skipped.
SECTIONS = [
    ("Golden suite (17 multi-hop questions), gpt-5.4-mini", "mini-4.1-test-suite.json", [
        ("Hardened (baseline)", "v2-hardened"),
        ("+ sparse BM25 + repair (Phase 1)", "v2-hardened-tuned"),
        ("+ fast path", "v2-hardened" + TUNED + "+fast_path"),
    ]),
    ("Simple one-hop suite (24 questions), gpt-5.4-mini", "simple_one_hop_suite.json", [
        ("Hardened (baseline)", "v2-hardened"),
        ("+ sparse BM25 + repair", "v2-hardened" + TUNED),
        ("+ fast path", "v2-hardened" + TUNED + "+fast_path"),
    ]),
    ("Golden suite, Claude Haiku 4.5 planner and answer: reasoning policy", "mini-4.1-test-suite.json", [
        ("No reasoning", "v2-hardened" + HAIKU + TUNED + "+fast_path"),
        ("Medium reasoning on every call", "v2-hardened" + HAIKU + "-reasoning-medium" + TUNED + "+fast_path"),
        ("Medium reasoning, selective", "v2-hardened" + HAIKU + "-reasoning-medium" + TUNED + "+fast_path+selective_reasoning"),
    ]),
]
SUITE_SIZES = {17: "mini-4.1-test-suite.json", 24: "simple_one_hop_suite.json"}


def load_runs() -> dict[tuple[str, str], list[dict]]:
    """(suite file, run_label) -> list of runs, each a list of result records."""
    runs: dict[tuple[str, str], list] = defaultdict(list)
    for path in sorted(RESULTS.glob("evaluation_agent_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        records = data["results"]
        if not records:
            continue
        # The results files do not record the input file; full runs are told apart by size.
        suite = SUITE_SIZES.get(len(records))
        if suite:
            runs[(suite, data["configuration"]["run_label"])].append(records)
    return runs


def stats(runs: list[list[dict]]) -> dict:
    records = [r for run in runs for r in run]
    def mean(key):
        values = [r[key] for r in records if isinstance(r.get(key), (int, float))]
        return st.mean(values) if values else None
    def pct(values, q):
        values = sorted(values)
        return values[min(len(values) - 1, round(q * (len(values) - 1)))]
    wall = [r["agent_wall_seconds"] for r in records]
    retrieval = [r["retrieval_latency_seconds"] for r in records]
    repaired = sum(1 for r in records for f in r.get("answer_facts", []) if f.get("repaired"))
    return {
        "runs": len(runs),
        "correct": st.mean(sum(r["correctness_majority"] == "pass" for r in run) for run in runs),
        "graded": mean("graded_correctness_mean"),
        "faithful": st.mean(sum(r.get("faithfulness") == "pass" for r in run) for run in runs),
        "citation_support": mean("citation_support_rate"),
        "wall_p50": st.median(wall), "wall_p90": pct(wall, 0.9), "wall_mean": st.mean(wall),
        "retrieval_p50": st.median(retrieval), "retrieval_mean": st.mean(retrieval),
        "planner_latency": mean("planner_latency_seconds"),
        "calls": mean("llm_calls_total"), "planner_calls": mean("planner_calls"),
        "retries": mean("verification_retries"), "repaired_per_query": repaired / len(records),
        "agent_cost": mean("agent_cost_usd"),
        "fast_share": sum(bool(r.get("fast_path_taken")) for r in records) / len(records),
        "fallback_share": sum(bool(r.get("fast_path_fallback")) for r in records) / len(records),
        "reasoning_calls": mean("reasoning_calls"),
        "run_cost": st.mean(sum(r["estimated_cost_usd"] for r in run) for run in runs),
    }


ROWS = [
    ("Correct (majority of 3 votes), per run", "correct", "{:.2f}"),
    ("Mean graded correctness", "graded", "{:.3f}"),
    ("Faithful answers, per run", "faithful", "{:.2f}"),
    ("Mean citation support rate", "citation_support", "{:.1%}"),
    ("Agent latency p50", "wall_p50", "{:.1f} s"),
    ("Agent latency p90", "wall_p90", "{:.1f} s"),
    ("Agent latency mean", "wall_mean", "{:.1f} s"),
    ("Retrieval time per query, p50 (all tool calls)", "retrieval_p50", "{:.2f} s"),
    ("Retrieval time per query, mean", "retrieval_mean", "{:.2f} s"),
    ("Planner model time per query, mean", "planner_latency", "{:.1f} s"),
    ("Agent model calls per query", "calls", "{:.2f}"),
    ("Planner calls per query", "planner_calls", "{:.2f}"),
    ("Verification retries per query", "retries", "{:.2f}"),
    ("Quotes repaired per query", "repaired_per_query", "{:.2f}"),
    ("Agent-only cost per query", "agent_cost", "${:.4f}"),
    ("Questions on the fast path", "fast_share", "{:.0%}"),
    ("Fast-path answers that fell back to the full agent", "fallback_share", "{:.0%}"),
    ("Model calls made with reasoning, per query", "reasoning_calls", "{:.2f}"),
    ("Cost per run (incl. judges)", "run_cost", "${:.2f}"),
]


def seed_identity(base: list[list[dict]], other: list[list[dict]]) -> str:
    """Share of questions whose seed search returned exactly the same ranked passages."""
    first = {r["id"]: r["agent_steps"][0]["ranked_unit_ids"] for r in base[0]}
    second = {r["id"]: r["agent_steps"][0]["ranked_unit_ids"] for r in other[0]}
    shared = [i for i in first if i in second]
    same = sum(first[i] == second[i] for i in shared)
    return f"{same}/{len(shared)}"


def main() -> None:
    runs = load_runs()
    lines = ["# Checkpoint 7.1 performance tuning: before vs after", "",
             "Generated by `tuning_report.py` from saved evaluation runs (no API calls). Baseline = the "
             "hardened agent; each tuned configuration adds performance features on top of it. Latency is the "
             "agent's own wall-clock time (judges excluded).", ""]
    for heading, suite, configurations in SECTIONS:
        present = [(label, key) for label, key in configurations if runs.get((suite, key))]
        if not present:
            continue
        computed = [(label, key, stats(runs[(suite, key)])) for label, key in present]
        lines += [f"## {heading}", "",
                  "| Metric | " + " | ".join(f"{label} ({s['runs']} runs)" for label, _k, s in computed) + " |",
                  "|---|" + "---|" * len(computed)]
        for row_label, key, fmt in ROWS:
            cells = [fmt.format(s[key]) if s[key] is not None else "n/a" for _l, _k, s in computed]
            lines.append(f"| {row_label} | " + " | ".join(cells) + " |")
        base_key = present[0][1]
        for label, key, _s in computed[1:]:
            lines.append("")
            lines.append(f"- Seed search identical to the baseline ({label}): "
                         f"{seed_identity(runs[(suite, base_key)], runs[(suite, key)])} questions")
        lines.append("")
    startup = {}
    for path in sorted(RESULTS.glob("evaluation_agent_v2-hardened-tuned*.json")):
        configuration = json.loads(path.read_text(encoding="utf-8"))["configuration"]
        if configuration.get("startup_seconds"):
            startup[path.name] = configuration["startup_seconds"]
    if startup:
        lines += ["## Start-up (tuned runs)", "", "| Run | " + " | ".join(next(iter(startup.values()))) + " |",
                  "|---|" + "---|" * len(next(iter(startup.values())))]
        for name, seconds in startup.items():
            lines.append(f"| `{name}` | " + " | ".join(f"{v} s" for v in seconds.values()) + " |")
        lines += ["", "Baseline start-up, from the Phase 0 measurements: BM25 tokenize + build 21 s on every start.", ""]
    (RESULTS / "tuning_before_after.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {RESULTS / 'tuning_before_after.md'}")


if __name__ == "__main__":
    main()
