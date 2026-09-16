r"""Capstone Checkpoint 3.1 - Evaluation Infrastructure and Baseline Diagnosis.

This step integrates the Wikipedia corpus and baseline hybrid retriever from
Checkpoint 2.1. The evaluation set, judge, and evaluation metrics remain ready
for later development.
"""

# %%
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import unicodedata
import warnings
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore")

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from rank_bm25 import BM25Okapi

CHECKPOINT_2_1_DIR = Path(__file__).parents[1] / "Checkpoint 2.1"
if str(CHECKPOINT_2_1_DIR) not in sys.path:
    sys.path.insert(0, str(CHECKPOINT_2_1_DIR))

from Extract_text_from_wikis import extract_wikipedia_text

# %%
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
LLM_MODEL = "openai/gpt-5.4-mini"
EMBEDDING_MODEL = "openai/text-embedding-3-small"
TEMPERATURE = 0.2
TOP_K = 3
CANDIDATE_POOL = 10
WEIGHT_BM25 = 0.5
WEIGHT_VECTOR = 0.5
LOG_PATH = Path.cwd() / "checkpoint_3_1_evaluation.log"
WIKIPEDIA_DIR = str(Path(__file__).with_name("Wikipedia_Film_Academy"))
WIKIPEDIA_CHROMA_DIR = str(Path(__file__).with_name("wikipedia_film_academy_chroma_db"))
GOLDEN_SUITE_PATH = Path(__file__).with_name("golden_suite.json")
RESULTS_DIR = Path(__file__).with_name("evaluation_results")

SCENARIO = "wikipedia"

ANSWER_SYSTEM = (
    "You are a helpful assistant. Answer the question using ONLY the provided "
    "documents. Cite factual claims with the exact source filename in square brackets. "
    "When quoting, use the form [filename.html] \"verbatim quotation\". If the "
    "documents do not contain the answer, say so rather than guessing."
)
JUDGE_SYSTEM = (
    "You are a strict evaluator of retrieval-augmented answers. Use only the supplied "
    "reference answer, required aspects, and retrieved context. Return valid JSON only."
)
QUALITY_LEVELS = {"complete", "substantially_complete", "partial", "incorrect"}
REFUSAL_OUTCOMES = {"appropriate_refusal", "over_refusal", "hallucinated"}


# %%
def check_api_key() -> str:
    load_dotenv()
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Use the OpenRouter API key "
            "provided for this program, put it in a .env file next to this "
            "script, and rerun."
        )
    return key


def make_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=LLM_MODEL,
        temperature=TEMPERATURE,
        api_key=check_api_key(),
        base_url=OPENROUTER_BASE_URL,
    )


def log(label: str, text: str) -> None:
    timestamp = datetime.now().isoformat(timespec="seconds")
    with LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(f"[{timestamp}] {label}\n{text}\n{'-' * 72}\n")


# %% [markdown]
# ## Wikipedia corpus and baseline hybrid retriever (from Checkpoint 2.1)

# %%
WIKIPEDIA_DOCS = extract_wikipedia_text(WIKIPEDIA_DIR)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=EMBEDDING_MODEL,
        api_key=check_api_key(),
        base_url=OPENROUTER_BASE_URL,
    )


def build_or_load_wikipedia_db() -> Chroma:
    if os.path.isdir(WIKIPEDIA_CHROMA_DIR) and os.listdir(WIKIPEDIA_CHROMA_DIR):
        print(f"Loading existing Wikipedia vector DB from {WIKIPEDIA_CHROMA_DIR}")
        return Chroma(
            persist_directory=WIKIPEDIA_CHROMA_DIR,
            embedding_function=get_embeddings(),
        )

    print("Building Wikipedia vector DB (first run - embedding whole articles)...")
    documents = [
        Document(page_content=text, metadata={"source": filename})
        for filename, text in WIKIPEDIA_DOCS
    ]
    db = Chroma.from_documents(
        documents,
        get_embeddings(),
        persist_directory=WIKIPEDIA_CHROMA_DIR,
    )
    print(f"Indexed {len(documents)} Wikipedia articles.")
    return db


def _normalize(scores: list[float], invert: bool = False) -> list[float]:
    if not scores:
        return []
    low, high = min(scores), max(scores)
    if high == low:
        return [0.5] * len(scores)
    normalized = [(score - low) / (high - low) for score in scores]
    return [1.0 - score for score in normalized] if invert else normalized


class WikipediaHybridRetriever:
    def __init__(self, documents: list[tuple[str, str]], db: Chroma):
        self._filenames = [filename for filename, _text in documents]
        self._texts = [text for _filename, text in documents]
        self._bm25 = BM25Okapi([_tokens(text) for text in self._texts])
        self._db = db

    def _bm25_top_k(self, query: str, k: int) -> list[tuple[str, str, float]]:
        scores = self._bm25.get_scores(_tokens(query))
        top = sorted(
            range(len(scores)),
            key=lambda index: scores[index],
            reverse=True,
        )[:k]
        return [
            (self._filenames[index], self._texts[index], float(scores[index]))
            for index in top
        ]

    def _vector_top_k(self, query: str, k: int) -> list[tuple[str, str, float]]:
        results = self._db.similarity_search_with_score(query, k=k)
        return [
            (document.metadata.get("source", "unknown"), document.page_content, float(score))
            for document, score in results
        ]

    def get_top_k(self, query: str, k: int) -> list[tuple[str, str, float]]:
        bm25_results = self._bm25_top_k(query, CANDIDATE_POOL)
        vector_results = self._vector_top_k(query, CANDIDATE_POOL)

        content_by_name: dict[str, str] = {}
        bm25_normalized: dict[str, float] = {}
        vector_normalized: dict[str, float] = {}

        for (name, content, _score), value in zip(
            bm25_results,
            _normalize([score for _name, _content, score in bm25_results]),
        ):
            content_by_name[name] = content
            bm25_normalized[name] = value

        for (name, content, _distance), value in zip(
            vector_results,
            _normalize(
                [distance for _name, _content, distance in vector_results],
                invert=True,
            ),
        ):
            content_by_name[name] = content
            vector_normalized[name] = value

        fused = [
            (
                name,
                content,
                WEIGHT_BM25 * bm25_normalized.get(name, 0.0)
                + WEIGHT_VECTOR * vector_normalized.get(name, 0.0),
            )
            for name, content in content_by_name.items()
        ]
        fused.sort(key=lambda item: item[2], reverse=True)
        return fused[:k]


_hybrid_retriever: WikipediaHybridRetriever | None = None


def retrieve(query: str, k: int = TOP_K) -> list[tuple[str, str, float]]:
    """Return the top whole Wikipedia articles using BM25-vector fusion."""
    global _hybrid_retriever
    if _hybrid_retriever is None:
        _hybrid_retriever = WikipediaHybridRetriever(
            WIKIPEDIA_DOCS,
            build_or_load_wikipedia_db(),
        )
    return _hybrid_retriever.get_top_k(query, k)


def answer(
    llm: ChatOpenAI,
    query: str,
    documents: list[tuple[str, str, float]],
) -> tuple[str, dict[str, float | int]]:
    context = "\n\n".join(
        f"[{filename}] {text}" for filename, text, _score in documents
    )
    messages = [
        SystemMessage(content=ANSWER_SYSTEM),
        HumanMessage(content=f"Documents:\n{context}\n\nQuestion: {query}"),
    ]
    return invoke_measured(llm, messages)


# %% [markdown]
# ## Step 2 - Evaluation metrics

# %%
def _message_text(response: Any) -> str:
    content = response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def _token_usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage_metadata", None) or {}
    metadata = getattr(response, "response_metadata", None) or {}
    fallback = metadata.get("token_usage", {})
    input_tokens = int(usage.get("input_tokens") or fallback.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or fallback.get("completion_tokens") or 0)
    total_tokens = int(
        usage.get("total_tokens")
        or fallback.get("total_tokens")
        or input_tokens + output_tokens
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def invoke_measured(
    llm: ChatOpenAI,
    messages: list[SystemMessage | HumanMessage],
) -> tuple[str, dict[str, float | int]]:
    started = time.perf_counter()
    response = llm.invoke(messages)
    usage: dict[str, float | int] = _token_usage(response)
    usage["latency_seconds"] = time.perf_counter() - started
    return _message_text(response), usage


def _json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise ValueError(f"Judge did not return JSON: {text[:200]!r}")
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("Judge response must be a JSON object")
    return value


def judge(
    llm: ChatOpenAI,
    answer_text: str,
    expected_answer: str,
    required_aspects: list[str],
    retrieved_context: str,
) -> tuple[dict[str, Any], dict[str, float | int]]:
    """Return binary, graded, aspect-coverage, faithfulness, and relevance judgments."""
    messages = [
        SystemMessage(content=JUDGE_SYSTEM),
        HumanMessage(
            content=(
                "Evaluate the response and return exactly one JSON object with keys:\n"
                "binary_correctness: 'pass' or 'fail';\n"
                "graded_correctness: 'complete', 'substantially_complete', 'partial', "
                "or 'incorrect';\n"
                "covered_aspect_indices: a list of 1-based indices supported by the response;\n"
                "faithfulness: 'pass' only if every material factual claim is supported "
                "by the retrieved context, otherwise 'fail';\n"
                "answer_relevance: 'pass' if the response addresses the question asked, "
                "even if incomplete or incorrect, 'fail' if it drifts onto a different "
                "question or ignores what was asked.\n\n"
                f"RESPONSE:\n{answer_text}\n\n"
                f"REFERENCE ANSWER:\n{expected_answer}\n\n"
                f"REQUIRED ASPECTS:\n{json.dumps(required_aspects, ensure_ascii=False)}\n\n"
                f"RETRIEVED CONTEXT:\n{retrieved_context}"
            )
        ),
    ]
    text, usage = invoke_measured(llm, messages)
    result = _json_object(text)
    binary = str(result.get("binary_correctness", "fail")).casefold()
    level = str(result.get("graded_correctness", "incorrect")).casefold()
    faithfulness = str(result.get("faithfulness", "fail")).casefold()
    answer_relevance = str(result.get("answer_relevance", "fail")).casefold()
    covered = {
        index
        for index in result.get("covered_aspect_indices", [])
        if isinstance(index, int) and 1 <= index <= len(required_aspects)
    }
    if binary not in {"pass", "fail"}:
        binary = "fail"
    if level not in QUALITY_LEVELS:
        level = "incorrect"
    if faithfulness not in {"pass", "fail"}:
        faithfulness = "fail"
    if answer_relevance not in {"pass", "fail"}:
        answer_relevance = "fail"
    return {
        "correctness": binary,
        "graded_correctness": level,
        "graded_correctness_score": {
            "complete": 1.0,
            "substantially_complete": 0.75,
            "partial": 0.5,
            "incorrect": 0.0,
        }[level],
        "covered_aspects": sorted(covered),
        "aspect_coverage": len(covered) / len(required_aspects) if required_aspects else 0.0,
        "faithfulness": faithfulness,
        "answer_relevance": answer_relevance,
    }, usage


def judge_refusal_behavior(
    llm: ChatOpenAI,
    item: dict[str, Any],
    answer_text: str,
    retrieved_context: str,
) -> tuple[str, dict[str, float | int]]:
    """Judge refusals and special adversarial behavior independently of correctness."""
    messages = [
        SystemMessage(
            content=(
                "You evaluate refusal behavior in a RAG answer. Return JSON only as "
                "{\"outcome\": value}, where value is appropriate_refusal, "
                "over_refusal, or hallucinated. appropriate_refusal means the response "
                "followed the required behavior, including answering normally when no "
                "refusal was warranted. over_refusal means it declined an answerable "
                "request without justification. hallucinated means it should have "
                "declined, corrected, qualified, or disambiguated but instead asserted "
                "unsupported information."
            )
        ),
        HumanMessage(
            content=(
                f"ANSWERABLE: {item['answerable']}\n"
                f"ADVERSARIAL KIND: {item.get('adversarial_kind')}\n"
                f"EXPECTED BEHAVIOR: {item.get('expected_behavior')}\n"
                f"QUESTION: {item['question']}\n"
                f"RESPONSE: {answer_text}\n"
                f"RETRIEVED CONTEXT:\n{retrieved_context}"
            )
        ),
    ]
    text, usage = invoke_measured(llm, messages)
    outcome = str(_json_object(text).get("outcome", "hallucinated")).casefold()
    if outcome not in REFUSAL_OUTCOMES:
        outcome = "hallucinated"
    return outcome, usage


# %% [markdown]
# ## Step 3 - Golden evaluation set

# %%
def _required_aspects(expected_answer: str) -> list[str]:
    """Create stable claim-sized aspects when an older suite lacks the field."""
    sentences = re.split(r"(?<=[.!?])\s+", expected_answer.strip())
    aspects = []
    for sentence in sentences:
        clauses = re.split(r";\s+", sentence)
        aspects.extend(clause.strip() for clause in clauses if clause.strip())
    return aspects


def my_eval_set(path: Path = GOLDEN_SUITE_PATH) -> list[dict[str, Any]]:
    """Load all records and expose the fields required by the evaluation harness."""
    data = json.loads(path.read_text(encoding="utf-8"))
    records = data.get("queries") if isinstance(data, dict) else data
    if not isinstance(records, list) or len(records) != 100:
        raise ValueError(f"Expected exactly 100 golden records in {path}")
    for item in records:
        question = item.get("question") or item.get("query")
        if not question:
            raise ValueError(f"Golden record {item.get('id', '<unknown>')} has no query")
        item["question"] = question
        item["grading_notes"] = item["expected_answer"]
        item["expected_sources"] = item.get("relevant_files", [])
        item["required_aspects"] = item.get("required_aspects") or _required_aspects(
            item["expected_answer"]
        )
    return records


def _source_metrics(
    expected_sources: list[str],
    retrieved_sources: list[str],
) -> dict[str, int | float | bool]:
    expected = {Path(source).name.casefold() for source in expected_sources}
    retrieved = {Path(source).name.casefold() for source in retrieved_sources}
    matches = expected & retrieved
    all_present = bool(expected) and expected <= retrieved
    return {
        "source_hit_at_k": int(bool(matches)),
        "source_recall_at_k": len(matches) / len(expected) if expected else 0.0,
        "source_precision_at_k": len(matches) / len(retrieved_sources) if retrieved_sources else 0.0,
        "source_recall_strict": 1.0 if all_present else 0.0,
        "all_required_present": all_present,
    }


_PUNCT_TRANSLATION = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})


def _normalize_evidence(text: str) -> str:
    text = unicodedata.normalize("NFKC", unescape(text)).translate(_PUNCT_TRANSLATION)
    return re.sub(r"\s+", " ", text).strip()


def _citation_metrics(
    response: str,
    hits: list[tuple[str, str, float]],
    expected_sources: list[str],
) -> dict[str, float | int | None]:
    retrieved = {Path(name).name.casefold(): text for name, text, _score in hits}
    expected = {Path(name).name.casefold() for name in expected_sources}
    citations = [
        Path(name).name.casefold()
        for name in re.findall(r"\[([^\]\n]+\.html)\]", response, flags=re.IGNORECASE)
    ]
    unique_citations = set(citations)
    citation_precision = (
        len(unique_citations & expected) / len(unique_citations)
        if unique_citations else None
    )
    unsupported_citation_rate = (
        len(unique_citations - set(retrieved)) / len(unique_citations)
        if unique_citations else None
    )

    quotes = [
        match.group(1) or match.group(2)
        for match in re.finditer(r'"([^"\n]{10,})"|“([^”\n]{10,})”', response)
    ]
    faithful = 0
    correctly_attributed = 0
    for quote in quotes:
        normalized_quote = _normalize_evidence(quote).casefold()
        matching_sources = {
            name
            for name, text in retrieved.items()
            if normalized_quote in _normalize_evidence(text).casefold()
        }
        if matching_sources:
            faithful += 1
        quote_position = response.find(quote)
        prefix = response[max(0, quote_position - 180):quote_position]
        nearby = re.findall(r"\[([^\]\n]+\.html)\]", prefix, flags=re.IGNORECASE)
        attributed = Path(nearby[-1]).name.casefold() if nearby else None
        if attributed and attributed in matching_sources:
            correctly_attributed += 1

    return {
        "response_quote_count": len(quotes),
        "quote_fidelity_rate": faithful / len(quotes) if quotes else None,
        "quote_attribution_accuracy": (
            correctly_attributed / len(quotes) if quotes else None
        ),
        "citation_count": len(unique_citations),
        "citation_precision": citation_precision,
        "unsupported_citation_rate": unsupported_citation_rate,
    }


def _estimated_cost_usd(input_tokens: int, output_tokens: int) -> float | None:
    input_rate = os.getenv("OPENROUTER_INPUT_USD_PER_MILLION")
    output_rate = os.getenv("OPENROUTER_OUTPUT_USD_PER_MILLION")
    if input_rate is None or output_rate is None:
        return None
    return (
        input_tokens * float(input_rate) + output_tokens * float(output_rate)
    ) / 1_000_000


# %% [markdown]
# ## Step 4 - Run the baseline evaluation

# %%
def _evaluate_item(
    llm: ChatOpenAI,
    item: dict[str, Any],
) -> tuple[dict[str, Any], list[tuple[str, str, float]]]:
    """Retrieve, answer, judge, and score a single golden-suite item."""
    hits = retrieve(item["question"], TOP_K)
    retrieved_context = "\n\n".join(
        f"[{filename}] {text}" for filename, text, _score in hits
    )
    if hits:
        response, answer_usage = answer(llm, item["question"], hits)
    else:
        response = "(no documents retrieved)"
        answer_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "latency_seconds": 0.0}
    quality, quality_usage = judge(
        llm,
        response,
        item["expected_answer"],
        item["required_aspects"],
        retrieved_context,
    )
    refusal_outcome, refusal_usage = judge_refusal_behavior(
        llm,
        item,
        response,
        retrieved_context,
    )
    retrieved_sources = [filename for filename, _text, _score in hits]
    source_metrics = _source_metrics(item["expected_sources"], retrieved_sources)
    citation_metrics = _citation_metrics(response, hits, item["expected_sources"])
    input_tokens = sum(
        int(usage["input_tokens"])
        for usage in (answer_usage, quality_usage, refusal_usage)
    )
    output_tokens = sum(
        int(usage["output_tokens"])
        for usage in (answer_usage, quality_usage, refusal_usage)
    )
    total_latency = sum(
        float(usage["latency_seconds"])
        for usage in (answer_usage, quality_usage, refusal_usage)
    )
    result = {
        "id": item["id"],
        "question": item["question"],
        "information_need": item["information_need"],
        "motivation": item["motivation"],
        "prior_familiarity": item["prior_familiarity"],
        "scope": item["scope"],
        "answerable": item["answerable"],
        "adversarial_kind": item.get("adversarial_kind"),
        "expected_sources": item["expected_sources"],
        "retrieved_sources": retrieved_sources,
        "required_aspects": item["required_aspects"],
        "response": response,
        **quality,
        **source_metrics,
        **citation_metrics,
        "refusal_outcome": refusal_outcome,
        "answer_latency_seconds": answer_usage["latency_seconds"],
        "judge_latency_seconds": float(quality_usage["latency_seconds"]) + float(refusal_usage["latency_seconds"]),
        "total_latency_seconds": total_latency,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "estimated_cost_usd": _estimated_cost_usd(input_tokens, output_tokens),
    }
    return result, hits


def _print_progress(
    item: dict[str, Any],
    result: dict[str, Any],
    hits: list[tuple[str, str, float]],
    index: int,
    total: int,
) -> None:
    retrieved = [(filename, score) for filename, _text, score in hits]
    print("=" * 72)
    print(f"{item['id']} ({index}/{total}): {item['question']}")
    print(
        f"  retrieved={retrieved}  correctness={result['correctness'].upper()} "
        f"grade={result['graded_correctness']} coverage={result['aspect_coverage']:.1%}"
    )
    print(f"  answer: {result['response']}")


def _write_results(
    results: list[dict[str, Any]],
    output_path: Path | None,
) -> tuple[Path, Path]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if output_path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = RESULTS_DIR / f"evaluation_{stamp}.json"
    output_path.write_text(
        json.dumps({"results": results}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    csv_path = output_path.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(results[0]))
        writer.writeheader()
        for result in results:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                for key, value in result.items()
            })
    return output_path, csv_path


def _print_summary(results: list[dict[str, Any]]) -> None:
    passes = sum(result["correctness"] == "pass" for result in results)
    relevant = sum(result["answer_relevance"] == "pass" for result in results)
    strict = sum(float(result["source_recall_strict"]) for result in results)
    mean_precision = sum(float(result["source_precision_at_k"]) for result in results) / len(results)
    normal_answerable = [
        result for result in results
        if result["answerable"] and result["adversarial_kind"] is None
    ]
    over_refusals = sum(
        result["refusal_outcome"] == "over_refusal" for result in normal_answerable
    )
    print("=" * 72)
    print(f"Binary correctness: {passes}/{len(results)} ({passes / len(results):.1%})")
    print(f"Answer relevance: {relevant}/{len(results)} ({relevant / len(results):.1%})")
    print(f"Strict source recall@{TOP_K}: {strict / len(results):.1%}")
    print(f"Mean source precision@{TOP_K}: {mean_precision:.1%}")
    for scope in ("single_document", "multi_document"):
        scoped = [result for result in results if result["scope"] == scope]
        if scoped:
            scoped_strict = sum(float(result["source_recall_strict"]) for result in scoped)
            print(
                f"  {scope}: {scoped_strict:.0f}/{len(scoped)} "
                f"({scoped_strict / len(scoped):.1%})"
            )
    print(
        f"Over-refusal rate: {over_refusals}/{len(normal_answerable)} "
        f"({over_refusals / len(normal_answerable):.1%})"
        if normal_answerable else "Over-refusal rate: not available"
    )
    quoted = [result for result in results if result["quote_fidelity_rate"] is not None]
    cited = [result for result in results if result["citation_precision"] is not None]
    if quoted:
        print(
            "Mean quote fidelity: "
            f"{sum(float(result['quote_fidelity_rate']) for result in quoted) / len(quoted):.1%}"
        )
        print(
            "Mean quote attribution accuracy: "
            f"{sum(float(result['quote_attribution_accuracy']) for result in quoted) / len(quoted):.1%}"
        )
    if cited:
        print(
            "Mean citation precision: "
            f"{sum(float(result['citation_precision']) for result in cited) / len(cited):.1%}"
        )
        print(
            "Mean unsupported citation rate: "
            f"{sum(float(result['unsupported_citation_rate']) for result in cited) / len(cited):.1%}"
        )
    for need in sorted({result["information_need"] for result in results}):
        group = [result for result in results if result["information_need"] == need]
        mean_latency = sum(float(result["total_latency_seconds"]) for result in group) / len(group)
        mean_tokens = sum(int(result["total_tokens"]) for result in group) / len(group)
        costs = [result["estimated_cost_usd"] for result in group]
        mean_cost = (
            sum(float(cost) for cost in costs) / len(costs)
            if all(cost is not None for cost in costs)
            else None
        )
        cost_text = f", mean estimated cost=${mean_cost:.6f}" if mean_cost is not None else ""
        print(
            f"{need}: mean latency={mean_latency:.2f}s, "
            f"mean tokens={mean_tokens:.0f}{cost_text}"
        )


def run_evaluation(limit: int | None = None, output_path: Path | None = None) -> None:
    llm = make_llm()
    eval_set = my_eval_set()
    if limit is not None:
        eval_set = eval_set[:limit]
    results: list[dict[str, Any]] = []
    print(f"Checkpoint 3.1 - baseline evaluation  |  scenario: {SCENARIO}\n")
    for index, item in enumerate(eval_set, 1):
        result, hits = _evaluate_item(llm, item)
        results.append(result)
        _print_progress(item, result, hits, index, len(eval_set))
        log(
            f"{item['id']}: {item['question']}",
            json.dumps(result, ensure_ascii=False, default=str),
        )

    output_path, csv_path = _write_results(results, output_path)
    _print_summary(results)
    print(f"Results JSON: {output_path.resolve()}")
    print(f"Results CSV:  {csv_path.resolve()}")


# %% [markdown]
# ## Step 5 - Validate the framework: can it catch a manipulated answer?

# %%
def validate_framework() -> None:
    llm = make_llm()
    item = my_eval_set()[0]
    hits = retrieve(item["question"])
    context = "\n\n".join(f"[{name}] {text}" for name, text, _score in hits)
    good, _usage = answer(llm, item["question"], hits)
    manipulated = "The 68th Academy Awards did not present a Best Picture award."
    good_result, _usage = judge(
        llm, good, item["expected_answer"], item["required_aspects"], context
    )
    manipulated_result, _usage = judge(
        llm,
        manipulated,
        item["expected_answer"],
        item["required_aspects"],
        context,
    )
    print("\n--- Framework validation ---")
    print(f"  correct answer     -> {good_result['correctness'].upper()}   (expected PASS)")
    print(f"  manipulated answer -> {manipulated_result['correctness'].upper()}   (expected FAIL)")
    print("  The framework works if it PASSES the correct answer and FAILS the manipulated one.")
    log(
        "FRAMEWORK VALIDATION",
        f"good={good_result['correctness']} manipulated={manipulated_result['correctness']}",
    )


# %%
def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the focused Wikipedia retriever.")
    parser.add_argument(
        "--limit",
        type=int,
        help="evaluate only the first N records (useful for a low-cost smoke test)",
    )
    parser.add_argument("--output", type=Path, help="path for results JSON")
    parser.add_argument(
        "--validate-framework",
        action="store_true",
        help="run the manipulated-answer judge check after evaluation",
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    run_evaluation(limit=args.limit, output_path=args.output)
    if args.validate_framework:
        validate_framework()


if __name__ == "__main__":
    main()

# %% [markdown]
# ## Step 6 - Complete the Capstone Checkpoint 3.1 worksheet