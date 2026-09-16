#!/usr/bin/env python3
"""
validate_golden_suite.py

Validate a golden test suite JSON file for a Wikipedia RAG evaluation corpus.

Checks performed:
  1. Schema conformance      - required fields, types, enum values
  2. File existence          - relevant_files and quote source_files resolve on disk
  3. Quote verification      - supporting quotes appear verbatim in tag-stripped HTML
  4. Quota compliance        - taxonomy distributions match targets
  5. Multi-document integrity- multi_document queries cite >= 2 distinct files
  6. Adversarial handling    - unanswerable queries flagged and quote-free
  7. Duplicate detection     - near-identical query text

Usage:
    python validate_golden_suite.py golden_suite.json ./corpus
    python validate_golden_suite.py golden_suite.json ./corpus --quote-threshold 0.90
    python validate_golden_suite.py golden_suite.json ./corpus --json-report report.json

Exit code 0 if no ERROR-level findings, 1 otherwise, 2 on fatal error.
"""

from __future__ import annotations

import argparse
import difflib
import html as html_mod
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import trafilatura

# --------------------------------------------------------------------------
# Expected taxonomy vocabularies (Singer / Lemmerich et al.)
# --------------------------------------------------------------------------

INFORMATION_NEEDS = {"fact_lookup", "overview", "in_depth"}

MOTIVATIONS = {
    "work_or_school",
    "personal_decision",
    "current_event",
    "media_reference",
    "conversation",
    "bored_random",
    "intrinsic_learning",
    "other",
}

FAMILIARITY = {"familiar", "unfamiliar"}

SCOPES = {"single_document", "multi_document"}

ADVERSARIAL_KINDS = {
    "unanswerable_from_corpus",
    "ambiguous_entity",
    "false_premise",
    "temporally_stale",
}

# Target counts for a 100-query suite.
QUOTA_TARGETS = {
    "information_need": {"fact_lookup": 35, "overview": 33, "in_depth": 32},
    "motivation": {
        "work_or_school": 18,
        "conversation": 24,
        "current_event": 17,
        "personal_decision": 13,
        "media_reference": 10,
        "intrinsic_learning": 12,
        "bored_random": 6,
    },
    "prior_familiarity": {"familiar": 55, "unfamiliar": 45},
    "scope": {"multi_document": 40, "single_document": 60},
}

# Tolerance (absolute count) before a quota deviation is reported.
QUOTA_TOLERANCE = {
    "information_need": 3,
    "motivation": 5,
    "prior_familiarity": 5,
    "scope": 5,
}

REQUIRED_FIELDS = {
    "id": str,
    "query": str,
    "information_need": str,
    "motivation": str,
    "prior_familiarity": str,
    "scope": str,
    "answerable": bool,
    "expected_answer": str,
    "required_aspects": list,
    "supporting_quotes": list,
    "relevant_files": list,
}

OPTIONAL_FIELDS = {
    "adversarial_kind": (str, type(None)),
    "expected_behavior": (str, type(None)),
    "difficulty_notes": (str, type(None)),
    "secondary_motivations": (list, type(None)),
}


# --------------------------------------------------------------------------
# Finding container
# --------------------------------------------------------------------------

class Finding:
    __slots__ = ("level", "check", "query_id", "message")

    def __init__(self, level: str, check: str, query_id: Optional[str], message: str):
        self.level = level
        self.check = check
        self.query_id = query_id
        self.message = message

    def as_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "check": self.check,
            "query_id": self.query_id,
            "message": self.message,
        }

    def __str__(self) -> str:
        qid = self.query_id if self.query_id is not None else "-"
        return f"[{self.level}] {self.check} ({qid}): {self.message}"


class Report:
    def __init__(self) -> None:
        self.findings: List[Finding] = []
        self.stats: Dict[str, Any] = {}

    def add(self, level: str, check: str, query_id: Optional[str], message: str) -> None:
        self.findings.append(Finding(level, check, query_id, message))

    def error(self, check: str, qid: Optional[str], msg: str) -> None:
        self.add("ERROR", check, qid, msg)

    def warn(self, check: str, qid: Optional[str], msg: str) -> None:
        self.add("WARN", check, qid, msg)

    def info(self, check: str, qid: Optional[str], msg: str) -> None:
        self.add("INFO", check, qid, msg)

    @property
    def n_errors(self) -> int:
        return sum(1 for f in self.findings if f.level == "ERROR")

    @property
    def n_warnings(self) -> int:
        return sum(1 for f in self.findings if f.level == "WARN")


# --------------------------------------------------------------------------
# HTML normalization
# --------------------------------------------------------------------------

_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
)
_SUP_REF_RE = re.compile(r"<sup\b[^>]*>.*?</sup>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_BRACKET_CITE_RE = re.compile(
    r"\[\s*(?:\d+|citation needed|note \d+|a|b|c)\s*\]", re.IGNORECASE
)
_WS_RE = re.compile(r"\s+")

_PUNCT_MAP = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2013": "-", "\u2014": "-", "\u2012": "-", "\u2015": "-", "\u2212": "-",
    "\u00a0": " ", "\u2007": " ", "\u202f": " ", "\u2009": " ", "\u200a": " ",
    "\u200b": "", "\u200c": "", "\u200d": "", "\ufeff": "",
    "\u2026": "...",
    "\u00ad": "",
}


def _map_punct(text: str) -> str:
    for src, dst in _PUNCT_MAP.items():
        if src in text:
            text = text.replace(src, dst)
    return text


def strip_html(raw: str, drop_refs: bool = True) -> str:
    """Convert raw HTML to normalized plain text suitable for substring matching."""
    text = _SCRIPT_STYLE_RE.sub(" ", raw)
    if drop_refs:
        text = _SUP_REF_RE.sub("", text)
    text = _TAG_RE.sub(" ", text)
    text = html_mod.unescape(text)
    if drop_refs:
        text = _BRACKET_CITE_RE.sub("", text)
    text = unicodedata.normalize("NFKC", text)
    text = _map_punct(text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def normalize_quote(quote: str) -> str:
    text = html_mod.unescape(quote)
    text = unicodedata.normalize("NFKC", text)
    text = _map_punct(text)
    text = _BRACKET_CITE_RE.sub("", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def fold(text: str) -> str:
    """Case-folded form for lenient comparison."""
    return text.casefold()


def best_fuzzy_ratio(needle: str, haystack: str, window_pad: int = 60) -> Tuple[float, str]:
    """
    Find the best approximate match of `needle` within `haystack`.
    Returns (ratio, best_window_text). Uses difflib on candidate windows anchored
    by shared long tokens to keep the search tractable on long articles.
    """
    if not needle:
        return 0.0, ""
    n = len(needle)
    if not haystack:
        return 0.0, ""

    tokens = [t for t in re.findall(r"\w+", needle) if len(t) > 4]
    tokens.sort(key=len, reverse=True)
    anchors: List[int] = []
    hay_fold = fold(haystack)
    for tok in tokens[:5]:
        start = 0
        tok_f = fold(tok)
        while len(anchors) < 40:
            idx = hay_fold.find(tok_f, start)
            if idx == -1:
                break
            anchors.append(idx)
            start = idx + len(tok_f)
    if not anchors:
        step = max(1, n // 2)
        anchors = list(range(0, max(1, len(haystack) - n), step))[:200]

    best_ratio = 0.0
    best_win = ""
    sm = difflib.SequenceMatcher(autojunk=False)
    sm.set_seq2(fold(needle))
    seen = set()
    for a in anchors:
        lo = max(0, a - window_pad)
        hi = min(len(haystack), a + n + window_pad)
        key = (lo // 20, hi // 20)
        if key in seen:
            continue
        seen.add(key)
        window = haystack[lo:hi]
        sm.set_seq1(fold(window))
        r = sm.quick_ratio()
        if r <= best_ratio:
            continue
        r = sm.ratio()
        if r > best_ratio:
            best_ratio = r
            best_win = window
        if best_ratio >= 0.999:
            break
    return best_ratio, best_win


# --------------------------------------------------------------------------
# Corpus index
# --------------------------------------------------------------------------

class Corpus:
    def __init__(self, root: Path, extensions: Iterable[str] = (".html", ".htm")):
        self.root = root
        self.extensions = tuple(e.lower() for e in extensions)
        self.by_name: Dict[str, List[Path]] = defaultdict(list)
        self.paths: List[Path] = []
        self._text_cache: Dict[Path, str] = {}
        self._index()

    def _index(self) -> None:
        if not self.root.exists():
            raise FileNotFoundError(f"Corpus directory not found: {self.root}")
        for p in self.root.rglob("*"):
            if p.is_file() and p.suffix.lower() in self.extensions:
                self.paths.append(p)
                self.by_name[p.name].append(p)
                self.by_name[p.name.casefold()].append(p)

    def resolve(self, ref: str) -> Optional[Path]:
        """Resolve a filename reference from the JSON to a real path."""
        ref = ref.strip().replace("\\", "/")
        cand = self.root / ref
        if cand.is_file():
            return cand
        direct = Path(ref)
        if direct.is_file():
            return direct
        name = Path(ref).name
        hits = self.by_name.get(name) or self.by_name.get(name.casefold())
        if hits:
            return hits[0]
        return None

    def text(self, path: Path) -> str:
        if path in self._text_cache:
            return self._text_cache[path]
        raw = path.read_text(encoding="utf-8", errors="replace")
        extracted = trafilatura.extract(raw)
        txt = normalize_quote(extracted) if extracted else strip_html(raw)
        self._text_cache[path] = txt
        return txt


# --------------------------------------------------------------------------
# Individual checks
# --------------------------------------------------------------------------

def check_schema(records: List[Dict[str, Any]], rep: Report) -> List[Dict[str, Any]]:
    valid: List[Dict[str, Any]] = []
    seen_ids: Counter = Counter()

    for i, rec in enumerate(records):
        qid = rec.get("id") if isinstance(rec, dict) else None
        label = qid if isinstance(qid, str) else f"index[{i}]"

        if not isinstance(rec, dict):
            rep.error("schema", label, "record is not a JSON object")
            continue

        ok = True
        for field, ftype in REQUIRED_FIELDS.items():
            if field not in rec:
                rep.error("schema", label, f"missing required field '{field}'")
                ok = False
            elif not isinstance(rec[field], ftype):
                rep.error(
                    "schema", label,
                    f"field '{field}' has type {type(rec[field]).__name__}, "
                    f"expected {ftype.__name__}",
                )
                ok = False

        for field, ftypes in OPTIONAL_FIELDS.items():
            if field in rec and not isinstance(rec[field], ftypes):
                rep.warn("schema", label, f"optional field '{field}' has unexpected type")

        enum_checks = [
            ("information_need", INFORMATION_NEEDS),
            ("motivation", MOTIVATIONS),
            ("prior_familiarity", FAMILIARITY),
            ("scope", SCOPES),
        ]
        for field, allowed in enum_checks:
            val = rec.get(field)
            if isinstance(val, str) and val not in allowed:
                rep.error("schema", label, f"'{field}' value {val!r} not in {sorted(allowed)}")
                ok = False

        ak = rec.get("adversarial_kind")
        if isinstance(ak, str) and ak and ak not in ADVERSARIAL_KINDS:
            rep.error(
                "schema", label,
                f"'adversarial_kind' {ak!r} not in {sorted(ADVERSARIAL_KINDS)}",
            )
            ok = False

        if isinstance(rec.get("query"), str) and not rec["query"].strip():
            rep.error("schema", label, "'query' is empty")
            ok = False

        for j, q in enumerate(rec.get("supporting_quotes", []) or []):
            if not isinstance(q, dict):
                rep.error("schema", label, f"supporting_quotes[{j}] is not an object")
                ok = False
                continue
            if not isinstance(q.get("text"), str) or not q.get("text", "").strip():
                rep.error("schema", label, f"supporting_quotes[{j}].text missing or empty")
                ok = False
            if not isinstance(q.get("source_file"), str) or not q.get("source_file", "").strip():
                rep.error("schema", label, f"supporting_quotes[{j}].source_file missing or empty")
                ok = False

        for j, f in enumerate(rec.get("relevant_files", []) or []):
            if not isinstance(f, str) or not f.strip():
                rep.error("schema", label, f"relevant_files[{j}] is not a non-empty string")
                ok = False

        if isinstance(qid, str):
            seen_ids[qid] += 1

        if ok:
            valid.append(rec)

    for qid, n in seen_ids.items():
        if n > 1:
            rep.error("schema", qid, f"duplicate id appears {n} times")

    return valid


def check_files(
    records: List[Dict[str, Any]], corpus: Corpus, rep: Report
) -> Dict[str, Dict[str, Path]]:
    resolved: Dict[str, Dict[str, Path]] = {}
    for rec in records:
        qid = rec["id"]
        rmap: Dict[str, Path] = {}
        unresolved: set = set()
        refs = list(rec.get("relevant_files", []))
        for q in rec.get("supporting_quotes", []) or []:
            refs.append(q["source_file"])
        for ref in refs:
            if ref in rmap or ref in unresolved:
                continue
            p = corpus.resolve(ref)
            if p is None:
                unresolved.add(ref)
                rep.error("files", qid, f"file not found in corpus: {ref!r}")
            else:
                rmap[ref] = p
        quote_srcs = {q["source_file"] for q in (rec.get("supporting_quotes") or [])}
        rel = set(rec.get("relevant_files", []))
        for src in quote_srcs:
            if src not in rel:
                rep.warn("files", qid, f"quote source {src!r} is not listed in relevant_files")
        if rec.get("answerable", True) and not rec.get("relevant_files"):
            rep.error("files", qid, "answerable query has empty relevant_files")
        resolved[qid] = rmap
    return resolved


def check_quotes(
    records: List[Dict[str, Any]],
    corpus: Corpus,
    resolved: Dict[str, Dict[str, Path]],
    rep: Report,
    threshold: float,
    min_quote_chars: int,
) -> Dict[str, Any]:
    exact = near = failed = total = 0
    near_band: List[Tuple[str, float, str]] = []

    for rec in records:
        qid = rec["id"]
        quotes = rec.get("supporting_quotes") or []
        if rec.get("answerable", True) and not quotes:
            rep.error("quotes", qid, "answerable query has no supporting_quotes")
        for j, q in enumerate(quotes):
            total += 1
            qt = normalize_quote(q["text"])
            if len(qt) < min_quote_chars:
                rep.warn(
                    "quotes", qid,
                    f"quote[{j}] is very short ({len(qt)} chars); weak evidence",
                )
            path = resolved.get(qid, {}).get(q["source_file"])
            if path is None:
                failed += 1
                continue
            doc = corpus.text(path)
            if qt in doc:
                exact += 1
                continue
            if fold(qt) in fold(doc):
                near += 1
                near_band.append((qid, 1.0, q["source_file"]))
                rep.warn(
                    "quotes", qid,
                    f"quote[{j}] matches {q['source_file']!r} only when case is ignored; "
                    f"fix capitalisation to make it verbatim",
                )
                continue
            ratio, _window = best_fuzzy_ratio(qt, doc)
            if ratio >= threshold:
                near += 1
                near_band.append((qid, ratio, q["source_file"]))
                rep.warn(
                    "quotes", qid,
                    f"quote[{j}] not exact but {ratio:.3f} similar in {q['source_file']!r}; "
                    f"likely markup or reference-marker drift",
                )
            else:
                failed += 1
                rep.error(
                    "quotes", qid,
                    f"quote[{j}] not found in {q['source_file']!r} "
                    f"(best similarity {ratio:.3f}); text={qt[:90]!r}",
                )
    return {
        "total": total, "exact": exact, "near": near, "failed": failed,
        "near_band": near_band,
    }


def check_multidoc(records: List[Dict[str, Any]], rep: Report) -> None:
    for rec in records:
        qid = rec["id"]
        files = {f.strip() for f in rec.get("relevant_files", [])}
        if rec.get("scope") == "multi_document":
            if len(files) < 2:
                rep.error(
                    "multidoc", qid,
                    f"scope=multi_document but only {len(files)} distinct file(s)",
                )
            srcs = {q["source_file"] for q in (rec.get("supporting_quotes") or [])}
            if rec.get("answerable", True) and len(srcs) < 2:
                rep.warn(
                    "multidoc", qid,
                    f"multi_document query draws quotes from only {len(srcs)} file(s); "
                    "synthesis may not be genuinely required",
                )
        elif rec.get("scope") == "single_document":
            if rec.get("answerable", True) and len(files) > 1:
                rep.warn(
                    "multidoc", qid,
                    f"scope=single_document but {len(files)} relevant files listed",
                )
        if rec.get("information_need") == "in_depth" and rec.get("scope") == "single_document":
            rep.info("multidoc", qid, "in_depth query scoped to a single document")


def check_adversarial(records: List[Dict[str, Any]], rep: Report) -> Dict[str, int]:
    counts: Counter = Counter()
    for rec in records:
        qid = rec["id"]
        kind = rec.get("adversarial_kind")
        answerable = rec.get("answerable", True)
        if kind:
            counts[kind] += 1
            if not rec.get("expected_behavior"):
                rep.error(
                    "adversarial", qid,
                    f"adversarial_kind={kind} but no expected_behavior given",
                )
            if kind == "unanswerable_from_corpus":
                if answerable:
                    rep.error("adversarial", qid, "unanswerable_from_corpus but answerable=true")
                if rec.get("supporting_quotes"):
                    rep.error(
                        "adversarial", qid,
                        "unanswerable_from_corpus must not carry supporting_quotes",
                    )
        else:
            if not answerable:
                rep.error("adversarial", qid, "answerable=false but no adversarial_kind set")
    total_adv = sum(counts.values())
    if total_adv < 10:
        rep.warn("adversarial", None, f"only {total_adv} adversarial queries; target is 10")
    missing = ADVERSARIAL_KINDS - set(counts)
    if missing:
        rep.warn("adversarial", None, f"no queries for adversarial kinds: {sorted(missing)}")
    return dict(counts)


def check_quotas(
    records: List[Dict[str, Any]], rep: Report, n_expected: int
) -> Dict[str, Dict[str, int]]:
    n = len(records)
    if n != n_expected:
        rep.warn("quotas", None, f"suite has {n} queries, expected {n_expected}")
    observed: Dict[str, Dict[str, int]] = {}
    for dim, targets in QUOTA_TARGETS.items():
        counts = Counter(rec.get(dim) for rec in records)
        observed[dim] = dict(counts)
        tol = QUOTA_TOLERANCE[dim]
        base = sum(targets.values()) or 1
        scale = n / base
        for level, target in targets.items():
            want = target * scale
            got = counts.get(level, 0)
            if abs(got - want) > tol:
                rep.warn(
                    "quotas", None,
                    f"{dim}.{level}: {got} vs target ~{want:.0f} (tolerance +/-{tol})",
                )
        for level in counts:
            if level not in targets and level is not None:
                rep.info("quotas", None, f"{dim}.{level}: {counts[level]} (no target defined)")
    return observed


def check_duplicates(records: List[Dict[str, Any]], rep: Report, threshold: float = 0.92) -> None:
    norm = [(rec["id"], _WS_RE.sub(" ", fold(rec["query"])).strip()) for rec in records]
    exact_map: Dict[str, List[str]] = defaultdict(list)
    for qid, q in norm:
        exact_map[q].append(qid)
    for q, ids in exact_map.items():
        if len(ids) > 1:
            rep.error("duplicates", None, f"identical query text shared by {ids}: {q[:70]!r}")
    for i in range(len(norm)):
        id_a, qa = norm[i]
        for j in range(i + 1, len(norm)):
            id_b, qb = norm[j]
            if abs(len(qa) - len(qb)) / max(len(qa), len(qb), 1) > 0.30:
                continue
            r = difflib.SequenceMatcher(None, qa, qb, autojunk=False).ratio()
            if r >= threshold and qa != qb:
                rep.warn("duplicates", None, f"{id_a} and {id_b} are {r:.2f} similar")


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

def validate(
    suite_path: Path,
    corpus_path: Path,
    quote_threshold: float = 0.88,
    n_expected: int = 100,
    min_quote_chars: int = 25,
) -> Report:
    rep = Report()
    data = json.loads(suite_path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        for key in ("queries", "suite", "items", "data"):
            if key in data and isinstance(data[key], list):
                records = data[key]
                break
        else:
            raise ValueError("JSON object has no list under 'queries'/'suite'/'items'/'data'")
    elif isinstance(data, list):
        records = data
    else:
        raise ValueError("Top-level JSON must be a list or an object containing a list")

    corpus = Corpus(corpus_path)
    rep.stats["corpus_files"] = len(corpus.paths)
    rep.stats["records_loaded"] = len(records)

    valid = check_schema(records, rep)
    rep.stats["records_valid_schema"] = len(valid)

    resolved = check_files(valid, corpus, rep)
    qstats = check_quotes(valid, corpus, resolved, rep, quote_threshold, min_quote_chars)
    rep.stats["quotes"] = {k: v for k, v in qstats.items() if k != "near_band"}
    check_multidoc(valid, rep)
    rep.stats["adversarial"] = check_adversarial(valid, rep)
    rep.stats["quotas"] = check_quotas(valid, rep, n_expected)
    check_duplicates(valid, rep)
    return rep


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Validate a Wikipedia RAG golden test suite.")
    ap.add_argument("suite", type=Path, help="Path to golden suite JSON")
    ap.add_argument("corpus", type=Path, help="Path to corpus directory of HTML files")
    ap.add_argument("--quote-threshold", type=float, default=0.88,
                    help="Fuzzy similarity floor for accepting a near-miss quote (default 0.88)")
    ap.add_argument("--expected-count", type=int, default=100,
                    help="Expected number of queries (default 100)")
    ap.add_argument("--min-quote-chars", type=int, default=25,
                    help="Warn on quotes shorter than this (default 25)")
    ap.add_argument("--json-report", type=Path, default=None,
                    help="Write machine-readable findings to this path")
    ap.add_argument("--quiet", action="store_true", help="Only print the summary")
    args = ap.parse_args(argv)

    try:
        rep = validate(
            args.suite, args.corpus,
            quote_threshold=args.quote_threshold,
            n_expected=args.expected_count,
            min_quote_chars=args.min_quote_chars,
        )
    except Exception as exc:
        print(f"[FATAL] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        order = {"ERROR": 0, "WARN": 1, "INFO": 2}
        for f in sorted(rep.findings, key=lambda f: (order[f.level], f.check, f.query_id or "")):
            print(f)

    q = rep.stats.get("quotes", {})
    print("\n--- summary ---")
    print(f"corpus files indexed : {rep.stats.get('corpus_files')}")
    print(f"records loaded       : {rep.stats.get('records_loaded')}")
    print(f"records valid schema : {rep.stats.get('records_valid_schema')}")
    if q:
        print(
            f"quotes exact/near/failed: "
            f"{q.get('exact')}/{q.get('near')}/{q.get('failed')} of {q.get('total')}"
        )
    print(f"errors               : {rep.n_errors}")
    print(f"warnings             : {rep.n_warnings}")

    if args.json_report:
        args.json_report.write_text(
            json.dumps(
                {"stats": rep.stats, "findings": [f.as_dict() for f in rep.findings]},
                indent=2, default=str,
            ),
            encoding="utf-8",
        )
        print(f"report written       : {args.json_report}")

    return 0 if rep.n_errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
