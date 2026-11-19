#!/usr/bin/env python3
"""Anonymize the examples/ documents and score identifier leaks + name coverage.

Ground truth: fictional entities planted in the example documents. Run from the
repo root:  python evaluate.py
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

from presidio_ro_anonymizer import build_analyzer, anonymize_text

HERE = Path(__file__).parent
EXAMPLES = HERE / "examples"

NAMES = {
    "01": ["Danila Maria-Ioana", "Rusu Andrei-Ionut", "Radu Irina", "Danila Sorin-Mihai",
            "Ursache Maria", "Cârstea Elena", "Popescu Georgiana"],
    "02": ["Danila Maria-Ioana", "Rusu Andrei-Ionut", "Cârstea Elena", "Danila Sorin-Mihai",
            "Ursache Maria", "Munteanu Vlad"],
    "03": ["Danila Maria-Ioana", "Popescu Georgiana", "Cârstea Elena"],
}
CNPS = {k: ["2850412220891"] for k in ("01", "02", "03")}
PHONES = {
    "01": ["0740 123 456", "0232 210 456", "0742.11.12.13"],
    "02": ["+40 740 123 456", "0742.11.12.13", "0753 999 111"],
    "03": ["0723 456 789"],
}
EMAILS = {"01": ["maria.danila@example.ro"], "02": ["munteanu.vlad@cabinet-exemplu.ro"], "03": []}
IDS = {"01": ["6331 5410 0008 2345"], "02": ["FA 08/452311"], "03": []}
KEYWORDS = ["externare", "pacient", "cardiacă", "control"]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).lower().strip()


def main() -> None:
    analyzer = build_analyzer()
    ok = True
    for f in sorted(EXAMPLES.glob("0*.txt")):
        doc = f.stem[:2]
        text = f.read_text(encoding="utf-8")
        anonymized, _ = anonymize_text(analyzer, text)
        ntext = norm(anonymized)

        leaked_cnp = sum(1 for c in CNPS[doc] if norm(c) in ntext)
        leaked_phones = sum(1 for p in PHONES[doc]
                            if re.sub(r"\D", "", p) in re.sub(r"\D", "", anonymized))
        leaked_emails = sum(1 for e in EMAILS[doc] if norm(e) in ntext)

        name_tokens = [t for n in NAMES[doc] for t in norm(n).replace("-", " ").split() if len(t) > 2]
        leaked_name_tokens = sum(1 for t in name_tokens if re.search(rf"\b{re.escape(t)}\b", ntext))

        print(f"[{doc}] CNP leaks: {leaked_cnp}/{len(CNPS[doc])} | "
              f"phones: {leaked_phones}/{len(PHONES[doc])} | "
              f"emails: {leaked_emails}/{len(EMAILS[doc])} | "
              f"name tokens remaining: {leaked_name_tokens}/{len(name_tokens)}")
        ok = ok and leaked_cnp == 0 and leaked_phones == 0 and leaked_emails == 0

    print("\nAll identifier categories protected." if ok else "\nWARNING: some identifiers leaked!")


if __name__ == "__main__":
    main()
