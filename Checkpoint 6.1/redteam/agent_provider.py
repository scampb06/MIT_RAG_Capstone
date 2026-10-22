"""promptfoo provider: the Wikipedia RAG agent (Checkpoint 5.1, or 7.1 hardened) as a red-team target.

promptfoo calls call_api(prompt, options, context) once per test:
- prompt: the user's question, rendered from the config's "{{question}}" template, so
  direct prompt injections arrive exactly as a user would type them.
- context["vars"]["injected_document"]: for indirect injection, attack text that the
  provider plants as a retrieved Wikipedia passage, ranked first in every passage search,
  as a poisoned article in the corpus would be. The real index is never modified.
- options["config"]:
  - module: "5.1" (default, the unhardened v2 agent), "7.1" (the hardened agent) or
    "7.1-tuned" (hardened plus performance tuning), so one config can compare them on
    identical inputs;
  - agent_version (5.1 only), planner_model, answer_model, reasoning_effort;
  - 7.1 only: disable (list of layers or performance features to switch off, for
    attribution), filter_model, max_planned_steps.

The tuned 7.1 script imports the hardened 7.1 script, which imports the 5.1 script; all are
used unchanged. 5.1 and 7.1 targets share one Toolbox; 7.1-tuned targets use the tuned
Toolbox (sparse BM25 index), so the index and graph load once per process and target type.
"""
from __future__ import annotations

import contextlib
import importlib.util
import pathlib
import sys
import threading
from typing import Any

CAPSTONE = pathlib.Path(__file__).resolve().parents[2]
SCRIPT_TUNED = CAPSTONE / "Checkpoint 7.1" / "capstone_checkpoint_7_1_tuned.py"
INJECTED_FILE = "Wikipedia_Editorial_Note.html"   # how the planted passage is labelled

_lock = threading.Lock()
_module = None
_toolboxes: dict[tuple, Any] = {}
_agents: dict[tuple, Any] = {}


def _tuned_module():
    """The tuned 7.1 module; the hardened 7.1 and the 5.1 modules are its m71 and m51."""
    global _module
    if _module is None:
        spec = importlib.util.spec_from_file_location("agent7_tuned", SCRIPT_TUNED)
        module = importlib.util.module_from_spec(spec)
        sys.modules["agent7_tuned"] = module    # TypedDict annotations resolve through sys.modules
        spec.loader.exec_module(module)
        _module = module
    return _module


def _agent_module():
    """The hardened 7.1 module (m71); its m51 attribute is the 5.1 module."""
    return _tuned_module().m71


def _disabled(config: dict[str, Any]) -> tuple[str, ...]:
    value = config.get("disable") or []
    names = value.split(",") if isinstance(value, str) else value
    return tuple(sorted({str(name).strip() for name in names if str(name).strip()}))


def _agent(config: dict[str, Any]):
    """One agent per configuration; the toolbox is shared by 5.1 and 7.1 agents."""
    m71 = _agent_module()
    m51 = m71.m51
    module = str(config.get("module", "5.1"))
    if module not in ("5.1", "7.1", "7.1-tuned"):
        raise ValueError(f"module must be '5.1', '7.1' or '7.1-tuned', not {module!r}")
    version = "v2" if module.startswith("7.1") else config.get("agent_version", "v2")
    disabled = _disabled(config)
    tables = version == "v2" and "tables" not in disabled
    key = (module, version, config.get("planner_model"), config.get("answer_model"),
           config.get("reasoning_effort"), disabled, config.get("filter_model"), config.get("max_planned_steps"))
    if key not in _agents:
        toolbox_key = (tables, module == "7.1-tuned" and "sparse_bm25" not in disabled)
        if toolbox_key not in _toolboxes:
            _toolboxes[toolbox_key] = (_tuned_module().TunedToolbox(tables=tables) if toolbox_key[1]
                                       else m51.Toolbox(tables=tables))
        toolbox = _toolboxes[toolbox_key]
        common = dict(planner_model=config.get("planner_model"), answer_model=config.get("answer_model"),
                      reasoning_effort=config.get("reasoning_effort"))
        if module.startswith("7.1"):
            agent_class = _tuned_module().TunedAgent if module == "7.1-tuned" else m71.HardenedAgent
            _agents[key] = agent_class(
                m51.adv.make_llm(), toolbox, disabled=set(disabled),
                filter_model=config.get("filter_model") or m71.FILTER_MODEL,
                max_planned_steps=int(config.get("max_planned_steps") or m51.MAX_PLANNED_STEPS), **common,
            )
        else:
            _agents[key] = m51.WikipediaAgent(m51.adv.make_llm(), toolbox, version,
                                              disabled=set(disabled), **common)
    return _agents[key]


def _plant(agent, injected: str):
    """Make every passage search return the injected text as its top hit."""
    m51 = _agent_module().m51
    tools = agent.tools
    original = tools.chunks

    def poisoned(query, parent="none", *args, **kwargs):
        hits, trace = original(query, parent, *args, **kwargs)
        planted = m51.Hit("injected-c00000", INJECTED_FILE, injected, 1.0)
        return [planted] + list(hits), {**trace, "planted_injection": True}

    tools.chunks = poisoned
    return original


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    config = (options or {}).get("config", {}) or {}
    variables = (context or {}).get("vars", {}) or {}
    injected = str(variables.get("injected_document") or "").strip()
    with _lock, contextlib.redirect_stdout(sys.stderr):   # keep stdout clean for promptfoo
        try:
            agent = _agent(config)
            original = _plant(agent, injected) if injected else None
            try:
                state = agent.run(prompt, mode="batch")
            finally:
                if original is not None:
                    agent.tools.chunks = original
            m71 = _agent_module()
            m51 = m71.m51
            metrics = m51.agent_metrics(None, state)
            usage = state["usage"]
            cost = m51._usage_cost(usage)
            return {
                "output": state["response"],
                "tokenUsage": {
                    "prompt": sum(int(u["input_tokens"]) for u in usage),
                    "completion": sum(int(u["output_tokens"]) for u in usage),
                    "total": sum(int(u["input_tokens"]) + int(u["output_tokens"]) for u in usage),
                },
                "cost": cost,
                "metadata": {
                    "module": str(config.get("module", "5.1")),
                    "agent_actions": metrics["agent_actions"],
                    "stop_reason": state["stop_reason"],
                    # Workflow size and per-role split, as in the 5.1 evaluation records.
                    # The cost filters match the 5.1 planner_cost_usd / answer_cost_usd fields,
                    # without the closed-book baseline the 5.1 answer cost includes.
                    "llm_calls_total": metrics["llm_calls_total"],
                    "planner_calls": metrics["planner_calls"],
                    "tool_llm_calls": metrics["tool_llm_calls"],          # clue step + decompose
                    "planned_steps": metrics["planned_steps"],
                    "verification_retries": metrics["verification_retries"],
                    "units_in_context": metrics["units_in_context"],
                    "context_chars": sum(len(hit.text) for hit in state["context"]),
                    "planner_input_tokens": metrics["planner_input_tokens"],
                    "planner_output_tokens": metrics["planner_output_tokens"],
                    "planner_latency_seconds": round(metrics["planner_latency_seconds"], 2),
                    "planner_cost_usd": m51._usage_cost([u for u in usage if u["role"] in ("plan", "clues")]),
                    "answer_cost_usd": m51._usage_cost([u for u in usage if u["role"] == "answer"]),
                    "filter_cost_usd": m51._usage_cost([u for u in usage if u["role"] == "filter"]),
                    "sources": list(dict.fromkeys(hit.source_file for hit in state["context"])),
                    "injected_document_in_context": any(hit.source_file == INJECTED_FILE for hit in state["context"]),
                    "planner_model": agent.planner_model,
                    "answer_model": agent.answer_model,
                    # 7.1 only: which layer acted (sanitizer rules, filter verdict, refusals, tags).
                    **m71.security_metrics(agent, state),
                    # 7.1-tuned only: fast-path and selective-reasoning decisions.
                    **(agent.extra_metrics(state) if hasattr(agent, "extra_metrics") else {}),
                },
            }
        except Exception as error:   # report, don't crash the whole red-team run
            return {"error": f"{type(error).__name__}: {error}"}
