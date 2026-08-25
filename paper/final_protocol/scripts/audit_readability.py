#!/usr/bin/env python3
"""Run deterministic readability and repetition checks on the manuscript.

The audit is intentionally mechanical. It identifies passages for human review;
it does not claim that a passing threshold makes scientific prose clear.
"""

from __future__ import annotations

import collections
import json
import re
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
FINAL = SCRIPT.parents[1]
MANUSCRIPT = FINAL / "main.tex"
MACROS = FINAL / "results_macros.tex"
OUTPUT = FINAL / "READABILITY_AUDIT.json"

WORD = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\\])")
STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "have", "in", "is", "it", "of", "on", "or", "that", "the",
    "their", "this", "to", "was", "were", "with", "within",
}


def macro_map(text: str) -> dict[str, str]:
    return {
        name: value
        for name, value in re.findall(
            r"\\newcommand\{\\([A-Za-z]+)\}\{([^{}]*)\}", text
        )
    }


def expand_simple_macros(text: str, macros: dict[str, str]) -> str:
    for name in sorted(macros, key=len, reverse=True):
        text = re.sub(rf"\\{re.escape(name)}(?:\{{\}})?", macros[name], text)
    return text


def strip_tex(text: str) -> str:
    text = re.sub(r"(?m)(?<!\\)%.*$", "", text)
    text = re.sub(r"\\(?:cite|label|ref|eqref|input|includegraphics)(?:\[[^]]*\])?\{[^{}]*\}", " ", text)
    text = re.sub(r"\\begin\{[^{}]+\}|\\end\{[^{}]+\}", "\n", text)
    text = re.sub(r"\\(?:section\*?|subsection\*?|paragraph|title|author|email|affiliation|date|caption|preprint)\{([^{}]*)\}", r"\n\1.\n", text)
    text = re.sub(r"\\[A-Za-z]+\*?(?:\[[^]]*\])?", " ", text)
    text = text.replace("---", " ").replace("--", "-")
    text = re.sub(r"[{}$&~_^]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return text


def source_line(tex: str, fragment: str) -> int | None:
    probe = " ".join(fragment.split())[:80]
    if not probe:
        return None
    words = probe.split()[:6]
    if not words:
        return None
    pattern = r"\s+".join(re.escape(word) for word in words)
    match = re.search(pattern, tex, re.I)
    return tex.count("\n", 0, match.start()) + 1 if match else None


def sentence_records(plain: str, tex: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for paragraph in re.split(r"\n\s*\n+", plain):
        paragraph = " ".join(paragraph.split()).strip()
        if not paragraph:
            continue
        for sentence in SENTENCE_END.split(paragraph):
            sentence = sentence.strip()
            words = WORD.findall(sentence)
            if len(words) < 3:
                continue
            records.append({
                "line": source_line(tex, sentence),
                "word_count": len(words),
                "sentence": sentence,
            })
    return records


def repeated_phrases(plain: str) -> list[dict[str, Any]]:
    words = [word.lower() for word in WORD.findall(plain)]
    counts: collections.Counter[tuple[str, ...]] = collections.Counter()
    for size in (5, 6):
        for index in range(len(words) - size + 1):
            phrase = tuple(words[index:index + size])
            if sum(word not in STOP for word in phrase) < 3:
                continue
            counts[phrase] += 1
    candidates = [
        {"phrase": " ".join(phrase), "count": count}
        for phrase, count in counts.items() if count >= 3
    ]
    candidates.sort(key=lambda row: (-row["count"], -len(row["phrase"]), row["phrase"]))
    return candidates[:40]


def paragraph_purposes(plain: str, tex: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for paragraph in re.split(r"\n\s*\n+", plain):
        normalized = " ".join(paragraph.split()).strip()
        words = WORD.findall(normalized)
        if len(words) < 15:
            continue
        first = SENTENCE_END.split(normalized, maxsplit=1)[0]
        lower = normalized.lower()
        if any(token in lower for token in ("limitation", "cannot", "does not", "unavailable")):
            purpose = "scope_or_limitation"
        elif any(token in lower for token in ("found", "covered", "disagreed", "mismatch", "estimate")):
            purpose = "result_or_evidence"
        elif any(token in lower for token in ("stage ", "protocol", "implementation", "resample", "records")):
            purpose = "method_or_definition"
        elif any(token in lower for token in ("prior work", "literature", "cite")):
            purpose = "prior_work"
        else:
            purpose = "narrative_or_interpretation"
        records.append({
            "line": source_line(tex, first),
            "word_count": len(words),
            "inferred_purpose": purpose,
            "topic_sentence": first,
        })
    return records


def abstract_word_count(tex: str, macros: dict[str, str]) -> int:
    match = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", tex, re.S)
    if not match:
        return 0
    return len(WORD.findall(strip_tex(expand_simple_macros(match.group(1), macros))))


def main() -> int:
    tex = MANUSCRIPT.read_text(encoding="utf-8")
    macros = macro_map(MACROS.read_text(encoding="utf-8"))
    expanded = expand_simple_macros(tex, macros)
    plain = strip_tex(expanded)
    sentences = sentence_records(plain, tex)
    sentence_lengths = [row["word_count"] for row in sentences]

    acronyms = sorted(set(re.findall(r"\b[A-Z][A-Z0-9/-]{1,}\b", plain)))
    acronym_occurrences = {
        acronym: len(re.findall(rf"(?<![A-Za-z0-9]){re.escape(acronym)}(?![A-Za-z0-9])", plain))
        for acronym in acronyms
    }
    defined_acronyms = sorted(set(
        match.group(1)
        for match in re.finditer(r"\([^()]*?\b([A-Z][A-Z0-9/-]{1,})\b[^()]*?\)", plain)
    ))
    conventional = {"A/A", "AI", "APS", "AST", "CRN", "DOI", "JSON", "REVTeX", "SHA-256"}
    undefined_acronyms = [a for a in acronyms if a not in defined_acronyms and a not in conventional]

    numbers = collections.Counter(re.findall(r"(?<![A-Za-z])(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?%?)(?![A-Za-z])", plain))
    repeated_numbers = [
        {"value": value, "count": count}
        for value, count in sorted(numbers.items(), key=lambda item: (-item[1], item[0]))
        if count >= 3
    ]

    core_terms = {
        "schedule matching": r"schedule (?:is|matching|matched)",
        "execution repeatability": r"execution repeatability is",
        "semantic event alignment": r"semantic event alignment is",
        "statistical admission": r"statistical admission (?:is|maps|means|denotes)",
        "recorded trace projection": r"(?:trace|recorded) projection",
        "analysis unit": r"analysis unit",
    }
    undefined_terms = [term for term, pattern in core_terms.items() if not re.search(pattern, plain, re.I)]

    abstract_words = abstract_word_count(tex, macros)
    long_sentences = [row for row in sentences if row["word_count"] > 40]
    severe_sentences = [row for row in sentences if row["word_count"] > 55]
    purposes = paragraph_purposes(plain, tex)
    abstract_match = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", tex, re.S)
    abstract_lines: tuple[int, int] | None = None
    if abstract_match:
        abstract_lines = (
            tex.count("\n", 0, abstract_match.start()) + 1,
            tex.count("\n", 0, abstract_match.end()) + 1,
        )
    long_paragraphs = [
        row for row in purposes
        if row["word_count"] > 220 and not (
            abstract_lines
            and row["line"] is not None
            and abstract_lines[0] <= row["line"] <= abstract_lines[1]
        )
    ]
    failures: list[str] = []
    if not 180 <= abstract_words <= 250:
        failures.append(f"abstract word count {abstract_words} is outside 180-250")
    if severe_sentences:
        failures.append(f"{len(severe_sentences)} sentences exceed 55 words")
    if long_paragraphs:
        failures.append(f"{len(long_paragraphs)} paragraphs exceed 220 words")
    if undefined_terms:
        failures.append("core terms lack detectable definitions: " + ", ".join(undefined_terms))

    report = {
        "schema_version": "manuscript-readability-audit-v1",
        "status": "PASS" if not failures else "FAIL",
        "scope": str(MANUSCRIPT.relative_to(FINAL)),
        "limitations": "Mechanical checks identify review targets but do not establish comprehension; independent human general-reader review remains required.",
        "status_scope": "MECHANICAL_ONLY",
        "human_comprehension_verified": False,
        "abstract_word_count": abstract_words,
        "mechanical_thresholds": {
            "abstract_words": [180, 250],
            "severe_sentence_words_above": 55,
            "nonabstract_paragraph_words_above": 220,
        },
        "sentence_length": {
            "sentence_count": len(sentences),
            "mean_words": round(sum(sentence_lengths) / len(sentence_lengths), 2) if sentences else 0,
            "maximum_words": max(sentence_lengths, default=0),
            "over_40_words": long_sentences,
            "over_55_words": severe_sentences,
        },
        "acronyms": {
            "distinct_count": len(acronyms),
            "occurrences": acronym_occurrences,
            "detectably_defined": defined_acronyms,
            "possibly_undefined_nonconventional": undefined_acronyms,
        },
        "repeated_phrases": repeated_phrases(plain),
        "repeated_numbers": repeated_numbers,
        "undefined_core_terms": undefined_terms,
        "warnings": (
            ["possibly undefined nonconventional acronyms: " + ", ".join(undefined_acronyms)]
            if undefined_acronyms else []
        ),
        "paragraph_purpose_audit": purposes,
        "failures": failures,
    }
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(OUTPUT), "failures": failures}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
