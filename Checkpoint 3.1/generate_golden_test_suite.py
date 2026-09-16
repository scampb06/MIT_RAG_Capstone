#!/usr/bin/env python3
"""Generate a golden Wikipedia evaluation suite with Claude Opus 5.

The script sends the instructions below the horizontal rule in
``golden_suite_generation_prompt.md`` and every item in ``WIKIPEDIA_DOCS`` to
Anthropic. It refuses to truncate the corpus: if the complete request cannot fit
Anthropic's request or context limits, it exits before making a generation call.

Usage:
    python generate_golden_test_suite.py --dry-run
    python generate_golden_test_suite.py
    python generate_golden_test_suite.py --output golden_suite.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

try:
    import anthropic
except ImportError as error:
    raise SystemExit(
        "The Anthropic SDK is required. Install it with: python -m pip install anthropic"
    ) from error

SCRIPT_DIR = Path(__file__).resolve().parent
CHECKPOINT_2_1_DIR = SCRIPT_DIR.parent / "Checkpoint 2.1"
WIKIPEDIA_DIR = SCRIPT_DIR / "Wikipedia_Film_Academy"
DEFAULT_PROMPT_PATH = SCRIPT_DIR / "golden_suite_generation_prompt.md"
DEFAULT_OUTPUT_PATH = SCRIPT_DIR / "golden_suite.json"
DEFAULT_MODEL = "claude-opus-5"

MAX_REQUEST_BYTES = 32 * 1024 * 1024
MODEL_CONTEXT_TOKENS = 1_000_000
DEFAULT_MAX_OUTPUT_TOKENS = 100_000
REQUEST_OVERHEAD_BYTES = 16_384

FOCUSED_CORPUS_OVERRIDE = """

## FOCUSED CORPUS OVERRIDE

The supplied corpus is the complete evaluation corpus for this run. It contains
exactly 60 connected Wikipedia articles about films, Academy Awards ceremonies and
categories, actors, directors, cinematographers, production designers, and related
awards. This focused description supersedes the broad-corpus description above.

Replace the requirement to cover every broad topical area with coverage of these
film-domain facets: award ceremonies and records; individual films; acting and
performers; directing and filmmakers; cinematography and production design; and
related international film awards. Include at least five queries involving each
facet; a query may cover more than one facet.

Use at least 60 distinct primary articles as originally required, which means every
article in this focused corpus must serve as a primary source for at least one record.
All other schema, quotation, taxonomy, distribution, adversarial, and self-check
requirements remain unchanged. Do not claim that an absent fact is unanswerable until
you have checked all 60 supplied articles.
"""


def load_extraction_function() -> Any:
    helper_path = CHECKPOINT_2_1_DIR / "Extract_text_from_wikis.py"
    spec = importlib.util.spec_from_file_location("extract_text_from_wikis", helper_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Could not load Wikipedia extraction helper: {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.extract_wikipedia_text


extract_wikipedia_text = load_extraction_function()
WIKIPEDIA_DOCS = extract_wikipedia_text(str(WIKIPEDIA_DIR))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a 100-query golden suite from the complete Wikipedia corpus."
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=DEFAULT_MAX_OUTPUT_TOKENS,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="load and size the complete corpus without calling Anthropic",
    )
    return parser.parse_args()


def require_api_key() -> str:
    load_dotenv(SCRIPT_DIR / ".env")
    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. Add it to the environment or to a .env file."
        )
    return api_key


def load_generation_prompt(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    separator = "\n---\n"
    if separator not in text:
        raise SystemExit(f"Prompt file has no horizontal-rule separator: {path}")
    prompt = text.split(separator, 1)[1].strip()
    if not prompt:
        raise SystemExit(f"Prompt instructions are empty: {path}")
    return prompt + FOCUSED_CORPUS_OVERRIDE


def serialize_corpus(documents: list[tuple[str, str]]) -> str:
    """Serialize every extracted article with an unambiguous filename boundary."""
    parts = [f"<wikipedia_corpus documents=\"{len(documents)}\">"]
    for filename, text in documents:
        parts.extend(
            (
                f"<document filename={json.dumps(filename, ensure_ascii=False)}>",
                text,
                "</document>",
            )
        )
    parts.append("</wikipedia_corpus>")
    return "\n".join(parts)


def build_messages(corpus: str) -> list[dict[str, Any]]:
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Use the complete extracted Wikipedia corpus below as the only "
                        "factual source. Follow the system instructions and return only "
                        "the requested JSON object.\n\n" + corpus
                    ),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
    ]


def request_size_bytes(
    model: str,
    prompt: str,
    messages: list[dict[str, Any]],
    max_output_tokens: int,
) -> int:
    payload = {
        "model": model,
        "max_tokens": max_output_tokens,
        "system": prompt,
        "messages": messages,
    }
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def ensure_request_size_fits(size_bytes: int) -> None:
    if size_bytes + REQUEST_OVERHEAD_BYTES <= MAX_REQUEST_BYTES:
        return
    raise SystemExit(
        "The complete corpus cannot be sent in one Anthropic Messages API request.\n"
        f"Serialized request: {size_bytes / 1024 / 1024:.2f} MiB\n"
        f"Messages API limit: {MAX_REQUEST_BYTES / 1024 / 1024:.0f} MiB\n"
        "Nothing was truncated and no generation request was made. Use a multi-pass "
        "sharded generation workflow, then consolidate and validate the candidates."
    )


def count_input_tokens(
    client: anthropic.Anthropic,
    model: str,
    prompt: str,
    messages: list[dict[str, Any]],
) -> int:
    count = client.messages.count_tokens(
        model=model,
        system=prompt,
        messages=messages,
    )
    return count.input_tokens


def ensure_context_fits(input_tokens: int, max_output_tokens: int) -> None:
    total_reserved = input_tokens + max_output_tokens
    if total_reserved <= MODEL_CONTEXT_TOKENS:
        return
    raise SystemExit(
        "The complete request does not fit Claude Opus 5's context window.\n"
        f"Input tokens: {input_tokens:,}\n"
        f"Reserved output tokens: {max_output_tokens:,}\n"
        f"Combined: {total_reserved:,}\n"
        f"Context limit: {MODEL_CONTEXT_TOKENS:,}\n"
        "No generation request was made. Use a multi-pass sharded workflow."
    )


def extract_json(message: Any) -> dict[str, Any]:
    text = "".join(
        block.text for block in message.content if getattr(block, "type", None) == "text"
    ).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise SystemExit(
            f"Claude returned invalid JSON at line {error.lineno}, column {error.colno}. "
            "The response was not written."
        ) from error
    if not isinstance(data, dict) or not isinstance(data.get("queries"), list):
        raise SystemExit("Claude's JSON must be an object containing a 'queries' array.")
    if len(data["queries"]) != 100:
        raise SystemExit(
            f"Claude returned {len(data['queries'])} queries instead of 100. "
            "The response was not written."
        )
    return data


def generate_suite(args: argparse.Namespace) -> None:
    prompt_path = args.prompt.resolve()
    output_path = args.output.resolve()
    prompt = load_generation_prompt(prompt_path)

    if not WIKIPEDIA_DOCS:
        raise SystemExit(f"No Wikipedia documents were extracted from: {WIKIPEDIA_DIR}")

    corpus = serialize_corpus(WIKIPEDIA_DOCS)
    messages = build_messages(corpus)
    size_bytes = request_size_bytes(
        args.model,
        prompt,
        messages,
        args.max_output_tokens,
    )

    print(f"Loaded {len(WIKIPEDIA_DOCS):,} Wikipedia documents.")
    print(f"Serialized request size: {size_bytes / 1024 / 1024:.2f} MiB.")
    ensure_request_size_fits(size_bytes)

    if args.dry_run:
        print("Dry run complete; the request fits the byte limit. No API call was made.")
        return

    client = anthropic.Anthropic(api_key=require_api_key())
    input_tokens = count_input_tokens(client, args.model, prompt, messages)
    print(f"Anthropic input-token count: {input_tokens:,}.")
    ensure_context_fits(input_tokens, args.max_output_tokens)

    print(f"Generating with {args.model}; this can take several minutes...")
    with client.messages.stream(
        model=args.model,
        max_tokens=args.max_output_tokens,
        system=prompt,
        messages=messages,
        thinking={"type": "adaptive", "display": "omitted"},
        output_config={"effort": "high"},
    ) as stream:
        message = stream.get_final_message()

    if message.stop_reason != "end_turn":
        raise SystemExit(
            f"Generation stopped with reason {message.stop_reason!r}; "
            "the incomplete response was not written."
        )

    suite = extract_json(message)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(suite, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(suite['queries'])} queries to: {output_path}")
    print(
        "Validate with: python validate_golden_suite.py "
        f'"{output_path}" "{WIKIPEDIA_DIR}"'
    )


def main() -> None:
    args = parse_args()
    if not 1 <= args.max_output_tokens <= 128_000:
        raise SystemExit("--max-output-tokens must be between 1 and 128000.")
    generate_suite(args)


if __name__ == "__main__":
    main()
