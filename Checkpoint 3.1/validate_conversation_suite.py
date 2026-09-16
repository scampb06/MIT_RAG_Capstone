#!/usr/bin/env python3
"""
validate_conversation_suite.py

Validate a multi-turn conversational test suite for a Wikipedia RAG chatbot.

Checks performed:
   1. Schema conformance        - session and turn fields, types, enum values
   2. Session metadata          - profile labels, declared vs actual turn counts
   3. Turn sequencing           - contiguous turn_index, standalone opening turn
   4. File existence            - relevant_files / quote sources / retrieval focus
   5. Quote verification        - verbatim match against tag-stripped HTML
   6. Context dependency        - standalone / referential / accumulative integrity
   7. Antecedent resolution     - referring expressions point at valid earlier turns
   8. Retrieval drift           - retrieval_should_shift vs expected_retrieval_focus
   9. Adversarial turns         - context-specific failure modes present and well-formed
  10. Corpus disjointness       - optional overlap check against the single-turn suite

Usage:
    python validate_conversation_suite.py conversations.json ./corpus
    python validate_conversation_suite.py conversations.json ./corpus \
        --golden-suite golden_suite.json
    python validate_conversation_suite.py conversations.json ./corpus \
        --json-report report.json --quiet

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
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# --------------------------------------------------------------------------
# Vocabularies
# --------------------------------------------------------------------------

INFORMATION_NEEDS = {"fact_lookup", "overview", "in_depth"}

MOTIVATIONS = {
    "work_or_school", "personal_decision", "current_event", "media_reference",
    "conversation", "bored_random", "intrinsic_learning", "other",
}

FAMILIARITY = {"familiar", "unfamiliar", "mixed"}

CURIOSITY_STYLES = {"hunter", "busybody", "dancer"}

CONTEXT_DEPENDENCY = {"standalone", "referential", "accumulative"}

TURN_ADVERSARIAL_KINDS = {
    "ambiguous_antecedent",
    "unintroduced_referent",
    "user_correction",
    "topic_return",
    "stale_context_trap",
}

PROFILE_IDS = {
    "assignment_researcher",
    "settling_an_argument",
    "late_night_wanderer",
    "trip_planner",
    "media_prompted_learner",
}

# Expected turn counts per profile (cap 20).
PROFILE_TURN_TARGETS = {
    "settling_an_argument": 8,
    "media_prompted_learner": 12,
    "trip_planner": 14,
    "assignment_researcher": 18,
    "late_night_wanderer": 20,
}

PROFILE_CURIOSITY = {
    "assignment_researcher": "hunter",
    "settling_an_argument": "hunter",
    "late_night_wanderer": "busybody",
    "trip_planner": "dancer",
    "media_prompted_learner": "dancer",
}

SESSION_REQUIRED = {
    "session_id": str,
    "profile": str,
    "curiosity_style": str,
    "information_need_anchor": str,
    "motivation_anchor": str,
    "prior_familiarity_anchor": str,
    "declared_turn_count": int,
    "session_arc": str,
    "turns": list,
}

TURN_REQUIRED = {
    "turn_index": int,
    "user_query": str,
    "context_dependency": str,
    "information_need": str,
    "answerable": bool,
    "expected_answer": str,
    "supporting_quotes": list,
    "relevant_files": list,
    "retrieval_should_shift": bool,
    "expected_retrieval_focus": list,
}

TURN_OPTIONAL = {
    "antecedents": (list, type(None)),
    "depends_on_turns": (list, type(None)),
    "adversarial_kind": (str, type(None)),
    "expected_behavior": (str, type(None)),
    "difficulty_notes": (str, type(None)),
    "referring_expressions": (list, type(None)),
}

MIN_ADVERSARIAL_PER_SESSION = 2
MAX_TURNS = 20


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------

class Finding:
    __slots__ = ("level", "check", "locus", "message")

    def __init__(self, level: str, check: str, locus: Optional[str], message: str):
        self.level, self.check, self.locus, self.message = level, check, locus, message

    def as_dict(self) -> Dict[str, Any]:
        return {"level": self.level, "check": self.check,
                "locus": self.locus, "message": self.message}

    def __str__(self) -> str:
        return f"[{self.level}] {self.check} ({self.locus or '-'}): {self.message}"


class Report:
    def __init__(self) -> None:
        self.findings: List[Finding] = []
        self.stats: Dict[str, Any] = {}

    def _add(self, lvl: str, chk: str, loc: Optional[str], msg: str) -> None:
        self.findings.append(Finding(lvl, chk, loc, msg))

    def error(self, chk: str, loc: Optional[str], msg: str) -> None:
        self._add("ERROR", chk, loc, msg)

    def warn(self, chk: str, loc: Optional[str], msg: str) -> None:
        self._add("WARN", chk, loc, msg)

    def info(self, chk: str, loc: Optional[str], msg: str) -> None:
        self._add("INFO", chk, loc, msg)

    @property
    def n_errors(self) -> int:
        return sum(1 for f in self.findings if f.level == "ERROR")

    @property
    def n_warnings(self) -> int:
        return sum(1 for f in self.findings if f.level == "WARN")


# --------------------------------------------------------------------------
# HTML normalization (shared with validate_golden_suite.py)
# --------------------------------------------------------------------------

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_SUP_REF_RE = re.compile(r"<sup\b[^>]*>.*?</sup>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_BRACKET_CITE_RE = re.compile(r"\[\s*(?:\d+|citation needed|note \d+|a|b|c)\s*\]", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")

_PUNCT_MAP = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2013": "-", "\u2014": "-", "\u2012": "-", "\u2015": "-", "\u2212": "-",
    "\u00a0": " ", "\u2007": " ", "\u202f": " ", "\u2009": " ", "\u200a": " ",
    "\u200b": "", "\u200c": "", "\u200d": "", "\ufeff": "", "\u2026": "...", "\u00ad": "",
}


def _map_punct(t: str) -> str:
    for a, b in _PUNCT_MAP.items():
        if a in t:
            t = t.replace(a, b)
    return t


def strip_html(raw: str) -> str:
    t = _SCRIPT_STYLE_RE.sub(" ", raw)
    t = _SUP_REF_RE.sub("", t)
    t = _TAG_RE.sub(" ", t)
    t = html_mod.unescape(t)
    t = _BRACKET_CITE_RE.sub("", t)
    t = unicodedata.normalize("NFKC", t)
    t = _map_punct(t)
    return _WS_RE.sub(" ", t).strip()


def normalize_quote(q: str) -> str:
    t = html_mod.unescape(q)
    t = unicodedata.normalize("NFKC", t)
    t = _map_punct(t)
    t = _BRACKET_CITE_RE.sub("", t)
    return _WS_RE.sub(" ", t).strip()


def fold(t: str) -> str:
    return t.casefold()


def best_fuzzy_ratio(needle: str, haystack: str, window_pad: int = 60) -> Tuple[float, str]:
    if not needle or not haystack:
        return 0.0, ""
    n = len(needle)
    tokens = sorted((t for t in re.findall(r"\w+", needle) if len(t) > 4), key=len, reverse=True)
    anchors: List[int] = []
    hay_fold = fold(haystack)
    for tok in tokens[:5]:
        start, tf = 0, fold(tok)
        while len(anchors) < 40:
            i = hay_fold.find(tf, start)
            if i == -1:
                break
            anchors.append(i)
            start = i + len(tf)
    if not anchors:
        step = max(1, n // 2)
        anchors = list(range(0, max(1, len(haystack) - n), step))[:200]
    best_r, best_w = 0.0, ""
    sm = difflib.SequenceMatcher(autojunk=False)
    sm.set_seq2(fold(needle))
    seen: Set[Tuple[int, int]] = set()
    for a in anchors:
        lo, hi = max(0, a - window_pad), min(len(haystack), a + n + window_pad)
        key = (lo // 20, hi // 20)
        if key in seen:
            continue
        seen.add(key)
        w = haystack[lo:hi]
        sm.set_seq1(fold(w))
        if sm.quick_ratio() <= best_r:
            continue
        r = sm.ratio()
        if r > best_r:
            best_r, best_w = r, w
        if best_r >= 0.999:
            break
    return best_r, best_w


# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------

class Corpus:
    def __init__(self, root: Path, extensions: Iterable[str] = (".html", ".htm")):
        self.root = root
        self.extensions = tuple(e.lower() for e in extensions)
        self.by_name: Dict[str, List[Path]] = defaultdict(list)
        self.paths: List[Path] = []
        self._cache: Dict[Path, str] = {}
        if not root.exists():
            raise FileNotFoundError(f"Corpus directory not found: {root}")
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in self.extensions:
                self.paths.append(p)
                self.by_name[p.name].append(p)
                self.by_name[p.name.casefold()].append(p)

    def resolve(self, ref: str) -> Optional[Path]:
        ref = ref.strip().replace("\\", "/")
        c = self.root / ref
        if c.is_file():
            return c
        d = Path(ref)
        if d.is_file():
            return d
        name = Path(ref).name
        hits = self.by_name.get(name) or self.by_name.get(name.casefold())
        return hits[0] if hits else None

    def text(self, path: Path) -> str:
        if path not in self._cache:
            self._cache[path] = strip_html(path.read_text(encoding="utf-8", errors="replace"))
        return self._cache[path]


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------

def check_session_schema(sessions: List[Dict[str, Any]], rep: Report) -> List[Dict[str, Any]]:
    valid: List[Dict[str, Any]] = []
    seen: Counter = Counter()
    for i, s in enumerate(sessions):
        if not isinstance(s, dict):
            rep.error("schema", f"session[{i}]", "session is not a JSON object")
            continue
        sid = s.get("session_id") if isinstance(s.get("session_id"), str) else f"session[{i}]"
        ok = True
        for f, t in SESSION_REQUIRED.items():
            if f not in s:
                rep.error("schema", sid, f"missing required session field '{f}'")
                ok = False
            elif not isinstance(s[f], t) or (t is int and isinstance(s[f], bool)):
                rep.error("schema", sid,
                          f"session field '{f}' is {type(s[f]).__name__}, expected {t.__name__}")
                ok = False
        for f, allowed in (("profile", PROFILE_IDS),
                           ("curiosity_style", CURIOSITY_STYLES),
                           ("information_need_anchor", INFORMATION_NEEDS),
                           ("motivation_anchor", MOTIVATIONS),
                           ("prior_familiarity_anchor", FAMILIARITY)):
            v = s.get(f)
            if isinstance(v, str) and v not in allowed:
                rep.error("schema", sid, f"session '{f}' value {v!r} not in {sorted(allowed)}")
                ok = False
        if isinstance(s.get("session_id"), str):
            seen[s["session_id"]] += 1
        if ok:
            valid.append(s)
    for sid, n in seen.items():
        if n > 1:
            rep.error("schema", sid, f"duplicate session_id appears {n} times")
    if len(sessions) != 5:
        rep.warn("schema", None, f"{len(sessions)} sessions found, expected 5")
    profiles = [s.get("profile") for s in valid]
    missing = PROFILE_IDS - set(profiles)
    if missing:
        rep.warn("schema", None, f"no session for profiles: {sorted(missing)}")
    for p, n in Counter(profiles).items():
        if n > 1:
            rep.warn("schema", None, f"profile {p!r} used by {n} sessions")
    return valid


def check_session_metadata(sessions: List[Dict[str, Any]], rep: Report) -> None:
    for s in sessions:
        sid = s["session_id"]
        prof = s.get("profile")
        turns = s.get("turns", [])
        declared = s.get("declared_turn_count")
        if isinstance(declared, int) and declared != len(turns):
            rep.error("session", sid,
                      f"declared_turn_count={declared} but {len(turns)} turns present")
        if len(turns) > MAX_TURNS:
            rep.error("session", sid, f"{len(turns)} turns exceeds cap of {MAX_TURNS}")
        if len(turns) < 2:
            rep.error("session", sid, "session has fewer than 2 turns; cannot test context")
        target = PROFILE_TURN_TARGETS.get(prof)
        if target and len(turns) != target:
            rep.warn("session", sid,
                     f"profile {prof!r} has {len(turns)} turns, target {target}")
        exp_style = PROFILE_CURIOSITY.get(prof)
        if exp_style and s.get("curiosity_style") != exp_style:
            rep.warn("session", sid,
                     f"profile {prof!r} declares curiosity_style "
                     f"{s.get('curiosity_style')!r}, expected {exp_style!r}")
        arc = s.get("session_arc", "")
        if isinstance(arc, str) and len(arc.strip()) < 40:
            rep.warn("session", sid, "session_arc is very short; should describe the trajectory")


def check_turn_schema(sessions: List[Dict[str, Any]], rep: Report) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for s in sessions:
        sid = s["session_id"]
        good: List[Dict[str, Any]] = []
        for i, t in enumerate(s.get("turns", [])):
            loc = f"{sid}#{i}"
            if not isinstance(t, dict):
                rep.error("schema", loc, "turn is not a JSON object")
                continue
            loc = f"{sid}#{t.get('turn_index', i)}"
            ok = True
            for f, ty in TURN_REQUIRED.items():
                if f not in t:
                    rep.error("schema", loc, f"missing required turn field '{f}'")
                    ok = False
                elif not isinstance(t[f], ty) or (ty is int and isinstance(t[f], bool)):
                    rep.error("schema", loc,
                              f"turn field '{f}' is {type(t[f]).__name__}, expected {ty.__name__}")
                    ok = False
            for f, tys in TURN_OPTIONAL.items():
                if f in t and not isinstance(t[f], tys):
                    rep.warn("schema", loc, f"optional turn field '{f}' has unexpected type")
            for f, allowed in (("context_dependency", CONTEXT_DEPENDENCY),
                               ("information_need", INFORMATION_NEEDS)):
                v = t.get(f)
                if isinstance(v, str) and v not in allowed:
                    rep.error("schema", loc, f"'{f}' value {v!r} not in {sorted(allowed)}")
                    ok = False
            ak = t.get("adversarial_kind")
            if isinstance(ak, str) and ak and ak not in TURN_ADVERSARIAL_KINDS:
                rep.error("schema", loc,
                          f"'adversarial_kind' {ak!r} not in {sorted(TURN_ADVERSARIAL_KINDS)}")
                ok = False
            if isinstance(t.get("user_query"), str) and not t["user_query"].strip():
                rep.error("schema", loc, "'user_query' is empty")
                ok = False
            for j, q in enumerate(t.get("supporting_quotes", []) or []):
                if not isinstance(q, dict):
                    rep.error("schema", loc, f"supporting_quotes[{j}] is not an object")
                    ok = False
                    continue
                if not isinstance(q.get("text"), str) or not q["text"].strip():
                    rep.error("schema", loc, f"supporting_quotes[{j}].text missing or empty")
                    ok = False
                if not isinstance(q.get("source_file"), str) or not q["source_file"].strip():
                    rep.error("schema", loc, f"supporting_quotes[{j}].source_file missing or empty")
                    ok = False
            if ok:
                good.append(t)
        out[sid] = good
    return out


def check_sequencing(sessions: List[Dict[str, Any]], rep: Report) -> None:
    for s in sessions:
        sid = s["session_id"]
        idxs = [t.get("turn_index") for t in s.get("turns", []) if isinstance(t, dict)]
        clean = [i for i in idxs if isinstance(i, int) and not isinstance(i, bool)]
        if len(clean) != len(idxs):
            rep.error("sequence", sid, "one or more turns have a non-integer turn_index")
            continue
        if not clean:
            continue
        expected = list(range(1, len(clean) + 1))
        if clean != expected:
            if sorted(clean) == expected:
                rep.error("sequence", sid, f"turn_index out of order: {clean}")
            else:
                rep.error("sequence", sid,
                          f"turn_index not contiguous 1..{len(clean)}: {clean}")
        dups = [i for i, n in Counter(clean).items() if n > 1]
        if dups:
            rep.error("sequence", sid, f"duplicate turn_index values: {sorted(dups)}")
        first = s.get("turns", [{}])[0]
        if isinstance(first, dict) and first.get("context_dependency") != "standalone":
            rep.error("sequence", sid,
                      f"first turn is {first.get('context_dependency')!r}; "
                      "opening turn must be standalone")


def check_files_and_quotes(
    sessions: List[Dict[str, Any]], corpus: Corpus, rep: Report,
    threshold: float, min_quote_chars: int,
) -> Dict[str, Any]:
    exact = near = failed = total = 0
    for s in sessions:
        sid = s["session_id"]
        for t in s.get("turns", []):
            if not isinstance(t, dict):
                continue
            loc = f"{sid}#{t.get('turn_index')}"
            rmap: Dict[str, Path] = {}
            unresolved: Set[str] = set()
            refs = list(t.get("relevant_files", []) or [])
            refs += list(t.get("expected_retrieval_focus", []) or [])
            for q in t.get("supporting_quotes", []) or []:
                if isinstance(q, dict) and isinstance(q.get("source_file"), str):
                    refs.append(q["source_file"])
            for ref in refs:
                if not isinstance(ref, str) or ref in rmap or ref in unresolved:
                    continue
                p = corpus.resolve(ref)
                if p is None:
                    unresolved.add(ref)
                    rep.error("files", loc, f"file not found in corpus: {ref!r}")
                else:
                    rmap[ref] = p
            rel = set(t.get("relevant_files", []) or [])
            for q in t.get("supporting_quotes", []) or []:
                if isinstance(q, dict) and q.get("source_file") not in rel:
                    rep.warn("files", loc,
                             f"quote source {q.get('source_file')!r} not in relevant_files")
            for f in t.get("expected_retrieval_focus", []) or []:
                if f not in rel:
                    rep.warn("files", loc,
                             f"expected_retrieval_focus {f!r} not in relevant_files")
            if t.get("answerable", True) and not t.get("relevant_files"):
                rep.error("files", loc, "answerable turn has empty relevant_files")

            quotes = t.get("supporting_quotes", []) or []
            if t.get("answerable", True) and not quotes:
                rep.error("quotes", loc, "answerable turn has no supporting_quotes")
            for j, q in enumerate(quotes):
                if not isinstance(q, dict):
                    continue
                total += 1
                qt = normalize_quote(q.get("text", ""))
                if len(qt) < min_quote_chars:
                    rep.warn("quotes", loc, f"quote[{j}] very short ({len(qt)} chars)")
                path = rmap.get(q.get("source_file"))
                if path is None:
                    failed += 1
                    continue
                doc = corpus.text(path)
                if qt in doc:
                    exact += 1
                    continue
                if fold(qt) in fold(doc):
                    near += 1
                    rep.warn("quotes", loc,
                             f"quote[{j}] matches {q['source_file']!r} only when case is ignored")
                    continue
                r, _ = best_fuzzy_ratio(qt, doc)
                if r >= threshold:
                    near += 1
                    rep.warn("quotes", loc,
                             f"quote[{j}] not exact but {r:.3f} similar in "
                             f"{q['source_file']!r}; likely markup drift")
                else:
                    failed += 1
                    rep.error("quotes", loc,
                              f"quote[{j}] not found in {q['source_file']!r} "
                              f"(best similarity {r:.3f}); text={qt[:90]!r}")
    return {"total": total, "exact": exact, "near": near, "failed": failed}


def check_context_dependency(sessions: List[Dict[str, Any]], rep: Report) -> Dict[str, int]:
    tally: Counter = Counter()
    for s in sessions:
        sid = s["session_id"]
        turns = [t for t in s.get("turns", []) if isinstance(t, dict)]
        for t in turns:
            loc = f"{sid}#{t.get('turn_index')}"
            dep = t.get("context_dependency")
            tally[dep] += 1
            idx = t.get("turn_index")
            ants = t.get("antecedents") or []
            deps = t.get("depends_on_turns") or []

            if dep == "standalone":
                if ants:
                    rep.error("context", loc, "standalone turn declares antecedents")
                if deps:
                    rep.error("context", loc, "standalone turn declares depends_on_turns")
            elif dep == "referential":
                # unintroduced_referent turns legitimately have no resolvable antecedent.
                if not ants and t.get("adversarial_kind") != "unintroduced_referent":
                    rep.error("context", loc, "referential turn has no antecedents")
                if not (t.get("referring_expressions") or []):
                    rep.warn("context", loc,
                             "referential turn lists no referring_expressions")
            elif dep == "accumulative":
                if not deps:
                    rep.error("context", loc,
                              "accumulative turn has no depends_on_turns")
                elif isinstance(idx, int) and len(deps) < 2:
                    rep.warn("context", loc,
                             "accumulative turn depends on only 1 prior turn; "
                             "may be merely referential")

            for d in deps:
                if not isinstance(d, int) or isinstance(d, bool):
                    rep.error("context", loc, f"depends_on_turns entry {d!r} is not an integer")
                elif isinstance(idx, int) and d >= idx:
                    rep.error("context", loc,
                              f"depends_on_turns references turn {d} at or after this turn ({idx})")
                elif d < 1:
                    rep.error("context", loc, f"depends_on_turns references invalid turn {d}")

        deps_present = {t.get("context_dependency") for t in turns}
        if "standalone" not in deps_present:
            rep.warn("context", sid, "session has no standalone control turns")
        if not ({"referential", "accumulative"} & deps_present):
            rep.error("context", sid,
                      "session has no context-dependent turns; does not test chat context")
        if "accumulative" not in deps_present:
            rep.warn("context", sid,
                     "session has no accumulative turns; hardest tier untested")
    return dict(tally)


def check_antecedents(sessions: List[Dict[str, Any]], rep: Report) -> None:
    for s in sessions:
        sid = s["session_id"]
        turns = [t for t in s.get("turns", []) if isinstance(t, dict)]
        by_idx = {t.get("turn_index"): t for t in turns}
        for t in turns:
            idx = t.get("turn_index")
            loc = f"{sid}#{idx}"
            for a in (t.get("antecedents") or []):
                if not isinstance(a, dict):
                    rep.error("antecedent", loc, "antecedent entry is not an object")
                    continue
                expr = a.get("expression")
                tgt = a.get("introduced_in_turn")
                ent = a.get("entity")
                if not isinstance(expr, str) or not expr.strip():
                    rep.error("antecedent", loc, "antecedent missing 'expression'")
                if not isinstance(ent, str) or not ent.strip():
                    rep.error("antecedent", loc, "antecedent missing 'entity'")
                if not isinstance(tgt, int) or isinstance(tgt, bool):
                    rep.error("antecedent", loc,
                              f"antecedent 'introduced_in_turn' {tgt!r} is not an integer")
                    continue
                if isinstance(idx, int) and tgt >= idx:
                    rep.error("antecedent", loc,
                              f"antecedent introduced_in_turn={tgt} is not earlier than {idx}")
                elif tgt not in by_idx:
                    rep.error("antecedent", loc,
                              f"antecedent introduced_in_turn={tgt} does not exist in session")
                else:
                    src = by_idx[tgt]
                    hay = fold(" ".join([
                        str(src.get("user_query", "")),
                        str(src.get("expected_answer", "")),
                        " ".join(str(x) for x in (src.get("relevant_files") or [])),
                        " ".join(str(q.get("text", "")) for q in
                                 (src.get("supporting_quotes") or [])
                                 if isinstance(q, dict)),
                    ])).replace("_", " ")
                    if isinstance(ent, str) and ent.strip():
                        toks = [w for w in re.findall(r"\w+", ent) if len(w) > 2]
                        if toks and not any(fold(w) in hay for w in toks):
                            rep.warn("antecedent", loc,
                                     f"entity {ent!r} not evidently present in turn {tgt}; "
                                     "verify the antecedent is genuinely introduced there")
                if isinstance(expr, str) and expr.strip():
                    if fold(expr.strip()) not in fold(str(t.get("user_query", ""))):
                        rep.warn("antecedent", loc,
                                 f"referring expression {expr!r} does not appear in user_query")


def check_retrieval_drift(sessions: List[Dict[str, Any]], rep: Report) -> Dict[str, int]:
    tally: Counter = Counter()
    for s in sessions:
        sid = s["session_id"]
        turns = [t for t in s.get("turns", []) if isinstance(t, dict)]
        prev_focus: Optional[Set[str]] = None
        shifts = 0
        for t in turns:
            idx = t.get("turn_index")
            loc = f"{sid}#{idx}"
            focus = t.get("expected_retrieval_focus") or []
            if not focus and t.get("answerable", True):
                rep.error("drift", loc, "answerable turn has empty expected_retrieval_focus")
                continue
            cur = {f for f in focus if isinstance(f, str)}
            declared = bool(t.get("retrieval_should_shift"))
            if declared:
                shifts += 1
            if prev_focus is not None:
                actually_shifted = bool(cur - prev_focus)
                if declared and not actually_shifted:
                    rep.error("drift", loc,
                              "retrieval_should_shift=true but expected_retrieval_focus "
                              "introduces no new document")
                if not declared and actually_shifted:
                    rep.error("drift", loc,
                              f"retrieval_should_shift=false but focus adds "
                              f"{sorted(cur - prev_focus)}")
            else:
                if not declared:
                    rep.warn("drift", loc,
                             "first turn declares retrieval_should_shift=false; "
                             "opening retrieval is always a shift")
            prev_focus = cur
        tally[sid] = shifts
        if turns and shifts == 0:
            rep.warn("drift", sid, "no retrieval shifts in session; drift is untested")
        if len(turns) >= 8 and shifts < 2:
            rep.warn("drift", sid,
                     f"only {shifts} retrieval shift(s) across {len(turns)} turns; "
                     "long session should move topic more than once")
    return dict(tally)


def check_adversarial(sessions: List[Dict[str, Any]], rep: Report) -> Dict[str, int]:
    tally: Counter = Counter()
    for s in sessions:
        sid = s["session_id"]
        turns = [t for t in s.get("turns", []) if isinstance(t, dict)]
        n_adv = 0
        for t in turns:
            idx = t.get("turn_index")
            loc = f"{sid}#{idx}"
            kind = t.get("adversarial_kind")
            if not kind:
                if not t.get("answerable", True):
                    rep.error("adversarial", loc,
                              "answerable=false but no adversarial_kind set")
                continue
            n_adv += 1
            tally[kind] += 1
            if not t.get("expected_behavior"):
                rep.error("adversarial", loc,
                          f"adversarial_kind={kind} but no expected_behavior given")
            if kind == "ambiguous_antecedent":
                ants = t.get("antecedents") or []
                if len(ants) < 2:
                    rep.error("adversarial", loc,
                              "ambiguous_antecedent must list 2+ candidate antecedents")
                if t.get("context_dependency") == "standalone":
                    rep.error("adversarial", loc,
                              "ambiguous_antecedent turn cannot be standalone")
            elif kind == "unintroduced_referent":
                if t.get("answerable", True):
                    rep.warn("adversarial", loc,
                             "unintroduced_referent is usually not answerable; verify")
                if t.get("antecedents"):
                    rep.error("adversarial", loc,
                              "unintroduced_referent must not resolve to a real antecedent")
            elif kind == "user_correction":
                deps = t.get("depends_on_turns") or []
                if not deps:
                    rep.error("adversarial", loc,
                              "user_correction must reference the turn being corrected")
            elif kind == "topic_return":
                deps = t.get("depends_on_turns") or []
                if isinstance(idx, int) and deps:
                    gap = idx - max(d for d in deps if isinstance(d, int))
                    if gap < 3:
                        rep.warn("adversarial", loc,
                                 f"topic_return only {gap} turn(s) after its referent; "
                                 "too close to test long-range memory")
                elif not deps:
                    rep.error("adversarial", loc,
                              "topic_return must reference the earlier turn returned to")
            elif kind == "stale_context_trap":
                if not t.get("retrieval_should_shift"):
                    rep.error("adversarial", loc,
                              "stale_context_trap must set retrieval_should_shift=true")
        if n_adv < MIN_ADVERSARIAL_PER_SESSION:
            rep.warn("adversarial", sid,
                     f"only {n_adv} adversarial turn(s); target is "
                     f"{MIN_ADVERSARIAL_PER_SESSION}+")
    missing = TURN_ADVERSARIAL_KINDS - set(tally)
    if missing:
        rep.warn("adversarial", None, f"no turns for adversarial kinds: {sorted(missing)}")
    return dict(tally)


def check_corpus_disjoint(
    sessions: List[Dict[str, Any]], golden_path: Optional[Path], rep: Report
) -> Optional[Dict[str, Any]]:
    if golden_path is None:
        return None
    try:
        data = json.loads(golden_path.read_text(encoding="utf-8"))
    except Exception as exc:
        rep.warn("disjoint", None, f"could not read golden suite: {exc}")
        return None
    recs = data.get("queries", data) if isinstance(data, dict) else data
    if not isinstance(recs, list):
        rep.warn("disjoint", None, "golden suite has unexpected structure")
        return None
    golden_files: Set[str] = set()
    for r in recs:
        if isinstance(r, dict):
            for f in r.get("relevant_files", []) or []:
                if isinstance(f, str):
                    golden_files.add(Path(f).name)
    convo_files: Set[str] = set()
    for s in sessions:
        for t in s.get("turns", []) or []:
            if isinstance(t, dict):
                for f in t.get("relevant_files", []) or []:
                    if isinstance(f, str):
                        convo_files.add(Path(f).name)
    overlap = golden_files & convo_files
    if overlap:
        rep.warn("disjoint", None,
                 f"{len(overlap)} article(s) shared with the single-turn suite: "
                 f"{sorted(overlap)[:8]}{'...' if len(overlap) > 8 else ''}")
    return {"golden_articles": len(golden_files),
            "conversation_articles": len(convo_files),
            "overlap": len(overlap)}


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

def validate(
    suite_path: Path, corpus_path: Path,
    quote_threshold: float = 0.88, min_quote_chars: int = 25,
    golden_suite: Optional[Path] = None,
) -> Report:
    rep = Report()
    data = json.loads(suite_path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        for k in ("sessions", "conversations", "suite", "data"):
            if k in data and isinstance(data[k], list):
                sessions = data[k]
                break
        else:
            raise ValueError(
                "JSON object has no list under 'sessions'/'conversations'/'suite'/'data'")
    elif isinstance(data, list):
        sessions = data
    else:
        raise ValueError("Top-level JSON must be a list or an object containing a list")

    corpus = Corpus(corpus_path)
    rep.stats["corpus_files"] = len(corpus.paths)
    rep.stats["sessions_loaded"] = len(sessions)

    valid = check_session_schema(sessions, rep)
    rep.stats["sessions_valid"] = len(valid)
    check_session_metadata(valid, rep)
    check_turn_schema(valid, rep)
    check_sequencing(valid, rep)
    rep.stats["quotes"] = check_files_and_quotes(
        valid, corpus, rep, quote_threshold, min_quote_chars)
    rep.stats["context_dependency"] = check_context_dependency(valid, rep)
    check_antecedents(valid, rep)
    rep.stats["retrieval_shifts"] = check_retrieval_drift(valid, rep)
    rep.stats["adversarial"] = check_adversarial(valid, rep)
    rep.stats["total_turns"] = sum(len(s.get("turns", []) or []) for s in valid)
    dj = check_corpus_disjoint(valid, golden_suite, rep)
    if dj:
        rep.stats["disjointness"] = dj
    return rep


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Validate a multi-turn conversational test suite for a Wikipedia RAG chatbot.")
    ap.add_argument("suite", type=Path, help="Path to conversation suite JSON")
    ap.add_argument("corpus", type=Path, help="Path to corpus directory of HTML files")
    ap.add_argument("--quote-threshold", type=float, default=0.88,
                    help="Fuzzy similarity floor for near-miss quotes (default 0.88)")
    ap.add_argument("--min-quote-chars", type=int, default=25,
                    help="Warn on quotes shorter than this (default 25)")
    ap.add_argument("--golden-suite", type=Path, default=None,
                    help="Optional single-turn suite JSON, to check article disjointness")
    ap.add_argument("--json-report", type=Path, default=None,
                    help="Write machine-readable findings to this path")
    ap.add_argument("--quiet", action="store_true", help="Only print the summary")
    args = ap.parse_args(argv)

    try:
        rep = validate(args.suite, args.corpus,
                       quote_threshold=args.quote_threshold,
                       min_quote_chars=args.min_quote_chars,
                       golden_suite=args.golden_suite)
    except Exception as exc:
        print(f"[FATAL] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        order = {"ERROR": 0, "WARN": 1, "INFO": 2}
        for f in sorted(rep.findings, key=lambda f: (order[f.level], f.check, f.locus or "")):
            print(f)

    q = rep.stats.get("quotes", {})
    cd = rep.stats.get("context_dependency", {})
    print("\n--- summary ---")
    print(f"corpus files indexed : {rep.stats.get('corpus_files')}")
    print(f"sessions loaded      : {rep.stats.get('sessions_loaded')}")
    print(f"sessions valid       : {rep.stats.get('sessions_valid')}")
    print(f"total turns          : {rep.stats.get('total_turns')}")
    if cd:
        print("context dependency   : "
              + ", ".join(f"{k}={v}" for k, v in sorted(cd.items()) if k))
    if q:
        print(f"quotes exact/near/failed: {q.get('exact')}/{q.get('near')}/"
              f"{q.get('failed')} of {q.get('total')}")
    print(f"errors               : {rep.n_errors}")
    print(f"warnings             : {rep.n_warnings}")

    if args.json_report:
        args.json_report.write_text(
            json.dumps({"stats": rep.stats,
                        "findings": [f.as_dict() for f in rep.findings]},
                       indent=2, default=str),
            encoding="utf-8")
        print(f"report written       : {args.json_report}")

    return 0 if rep.n_errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
