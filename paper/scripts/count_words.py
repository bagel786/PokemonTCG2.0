#!/usr/bin/env python3
"""Reproducible conservative word count for the REVTeX source."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "paper/main.tex"


def prose_words(source: str) -> list[str]:
    source = re.sub(r"(?m)(?<!\\)%.*$", " ", source)
    source = re.sub(r"\\begin\{(?:equation\*?|align\*?|ruledtabular|tabular)\}.*?"
                    r"\\end\{(?:equation\*?|align\*?|ruledtabular|tabular)\}",
                    " ", source, flags=re.S)
    source = re.sub(r"\$.*?\$", " ", source, flags=re.S)
    source = re.sub(r"\\(?:cite|ref|eqref|label|input|includegraphics|bibliography)"
                    r"(?:\[[^\]]*\])?\{[^{}]*\}", " ", source)
    source = re.sub(r"\\(?:begin|end)\{[^{}]*\}", " ", source)
    source = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?", " ", source)
    source = source.replace("\\%", " percent ").replace("~", " ")
    source = source.replace("{", " ").replace("}", " ").replace("\\", " ")
    return re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)*", source)


def segment(text: str, start: str, end: str | None) -> str:
    begin = text.index(start) + len(start)
    finish = text.index(end, begin) if end else len(text)
    return text[begin:finish]


def main() -> int:
    text = SOURCE.read_text(encoding="utf-8")
    abstract = segment(text, r"\begin{abstract}", r"\end{abstract}")
    article = segment(text, r"\maketitle", r"\appendix")
    appendices = segment(text, r"\appendix", r"\bibliography")
    result = {
        "method": (
            "paper/scripts/count_words.py regex count of alphabetic prose tokens; "
            "excludes preamble, display math, table bodies, citations, references, and bibliography"
        ),
        "abstract_words": len(prose_words(abstract)),
        "main_article_words": len(prose_words(article)),
        "appendix_words": len(prose_words(appendices)),
    }
    result["abstract_plus_main_words"] = result["abstract_words"] + result["main_article_words"]
    result["total_including_appendices"] = result["abstract_plus_main_words"] + result["appendix_words"]
    output = ROOT / "paper/word_count.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
