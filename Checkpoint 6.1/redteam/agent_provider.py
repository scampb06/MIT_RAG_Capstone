"""promptfoo provider: the Checkpoint 5.1 Wikipedia RAG agent as a red-team target.

promptfoo calls call_api(prompt, options, context) once per test:
- prompt: the user's question, rendered from the config's "{{question}}" template, so
  direct prompt injections arrive exactly as a user would type them.
- context["vars"]["injected_document"]: for indirect injection, attack text that the
  provider plants as a retrieved Wikipedia passage, ranked first in every passage search,
  as a poisoned article in the corpus would be. The real index is never modified.
- options["config"]: agent_version, planner_model, answer_model, reasoning_effort, so one
  config can probe several rungs of the model ladder.

The 5.1 script is imported unchanged; the index and graph load once per process.
"""
from __future__ import annotations

import contextlib
import importlib.util
import pathlib
import sys
import threading
from typing import Any

CHECKPOINT_5_1 = pathlib.Path(__file__).resolve().parents[2] / "Checkpoint 5.1"
SCRIPT = CHECKPOINT_5_1 / "capstone_checkpoint_5_1_agent_rag_solution.py"
INJECTED_FILE = "Wikipedia_Editorial_Note.html"   # how the planted passage is labelled

_lock = threading.Lock()
_module = None
_toolboxes: dict[bool, Any] = {}
_agents: dict[tuple, Any] = {}


def _agent_module():
    global _module
    if _module is None:
        spec = importlib.util.spec_from_file_location("agent5", SCRIPT) # load the 5.1 agent script as a module
        module = importlib.util.module_from_spec(spec) # create a new module object from the spec
        sys.modules["agent5"] = module # register the module in sys.modules
        spec.loader.exec_module(module) # execute the module in its own namespace
        _module = module # cache the module for future use
    return _module


def _agent(config: dict[str, Any]):
    """One agent per model configuration; the toolbox is shared."""
    m = _agent_module()
    version = config.get("agent_version", "v2")
    tables = version == "v2"
    key = (version, config.get("planner_model"), config.get("answer_model"), config.get("reasoning_effort"))
    if key not in _agents:
        if tables not in _toolboxes:
            _toolboxes[tables] = m.Toolbox(tables=tables)
        _agents[key] = m.WikipediaAgent(
            m.adv.make_llm(), _toolboxes[tables], version,
            planner_model=config.get("planner_model"), answer_model=config.get("answer_model"),
            reasoning_effort=config.get("reasoning_effort"),
        )
    return _agents[key]


def _plant(agent, injected: str):
    """Make every passage search return the injected text as its top hit."""
    m = _agent_module()
    tools = agent.tools
    original = tools.chunks

    def poisoned(query, parent="none", *args, **kwargs):
        hits, trace = original(query, parent, *args, **kwargs)
        planted = m.Hit("injected-c00000", INJECTED_FILE, injected, 1.0)
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
            m = _agent_module()
            metrics = m.agent_metrics(None, state)
            usage = state["usage"]
            cost = m._usage_cost(usage)
            return {
                "output": state["response"],
                "tokenUsage": {
                    "prompt": sum(int(u["input_tokens"]) for u in usage),
                    "completion": sum(int(u["output_tokens"]) for u in usage),
                    "total": sum(int(u["input_tokens"]) + int(u["output_tokens"]) for u in usage),
                },
                "cost": cost,
                "metadata": {
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
                    "planner_cost_usd": m._usage_cost([u for u in usage if u["role"] in ("plan", "clues")]),
                    "answer_cost_usd": m._usage_cost([u for u in usage if u["role"] == "answer"]),
                    "sources": list(dict.fromkeys(hit.source_file for hit in state["context"])),
                    "injected_document_in_context": any(hit.source_file == INJECTED_FILE for hit in state["context"]),
                    "planner_model": agent.planner_model,
                    "answer_model": agent.answer_model,
                },
            }
        except Exception as error:   # report, don't crash the whole red-team run
            return {"error": f"{type(error).__name__}: {error}"}
