#!/usr/bin/env python3
"""
Romanian PII anonymizer built on Microsoft Presidio.

Stack (all free / open source):
  - Presidio Analyzer (MIT) as the framework
  - spaCy `ro_core_news_lg` as the Romanian NER engine (names, locations, dates)
  - Custom recognizers:
      * Romanian CNP (personal numeric code) with FULL checksum validation
      * 16-digit health-card style numbers
  - Presidio predefined recognizers: Email, Phone (RO region), IBAN

Why this exists: out of the box, Presidio is English-oriented. It has no Romanian
NER model configured and no CNP recognizer, so on Romanian text it finds almost
nothing. This script wires the pieces together (and works around a subtle gotcha:
when you build your own RecognizerRegistry, you MUST add `SpacyRecognizer`
explicitly, otherwise NER silently returns nothing).

Usage:
    python presidio_ro_anonymizer.py document.txt                # print anonymized text
    python presidio_ro_anonymizer.py document.txt -o out.txt     # save anonymized text
    python presidio_ro_anonymizer.py folder_with_txts -o outdir  # batch mode

Requires:
    pip install "presidio-analyzer>=2.2.356" "spacy>=3.7,<4"
    python -m spacy download ro_core_news_lg

License: MIT
"""

import argparse
import json
import pathlib
import sys

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import (
    EmailRecognizer,
    IbanRecognizer,
    PhoneRecognizer,
    SpacyRecognizer,
)

# ---------------------------------------------------------------------------
# Custom recognizers
# ---------------------------------------------------------------------------

CNP_WEIGHTS = [2, 7, 9, 1, 4, 6, 3, 5, 8, 2, 7, 9]


def cnp_checksum_valid(cnp: str) -> bool:
    """Validate a Romanian CNP (personal numeric code) checksum.

    Format: S YY MM DD JJ NNN C  (13 digits).
    S: 1-9 (1/2 = born 1900-2099, 3/4 = 1800s, 5/6 = 2000s, 7/8/9 = residents).
    JJ: county code 01-52. C: checksum per the official algorithm.
    """
    if len(cnp) != 13 or not cnp.isdigit() or cnp[0] not in "1234569":
        return False
    year_part = int(cnp[1:3])
    month = int(cnp[3:5])
    day = int(cnp[5:7])
    county = int(cnp[7:9])
    if not (1 <= month <= 12 and 1 <= day <= 31 and 1 <= county <= 52):
        return False
    checksum = sum(int(d) * w for d, w in zip(cnp[:12], CNP_WEIGHTS)) % 11
    checksum = 1 if checksum == 10 else checksum
    return checksum == int(cnp[12])


class RomanianCnpRecognizer(PatternRecognizer):
    """Detects Romanian CNPs (13 digits) and keeps only checksum-valid ones."""

    PATTERNS = [Pattern("cnp-13-digits", r"\b[1-9]\d{12}\b", 0.4)]
    CONTEXT = ["cnp", "cod numeric personal"]

    def __init__(self, **kwargs):
        super().__init__(
            supported_entity="CNP_RO",
            supported_language="ro",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            name="RO CNP Recognizer",
            **kwargs,
        )

    def validate_result(self, pattern_text: str):
        # Returning False invalidates the match (e.g. a 13-digit order number).
        return True if cnp_checksum_valid(pattern_text.strip()) else False


class Card16Recognizer(PatternRecognizer):
    """16-digit numbers grouped in fours (health-card style identifiers)."""

    PATTERNS = [Pattern("card-16-grouped", r"\b\d{4} \d{4} \d{4} \d{4}\b", 0.4)]
    CONTEXT = ["card", "sănătate"]

    def __init__(self, **kwargs):
        super().__init__(
            supported_entity="RO_CARD16",
            supported_language="ro",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            name="RO Card16 Recognizer",
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Analyzer setup
# ---------------------------------------------------------------------------

# Map the Romanian spaCy model's labels to Presidio entity types.
NER_LABEL_MAPPING = {
    "PERSON": "PERSON",
    "LOC": "LOCATION",
    "GPE": "LOCATION",
    "FACILITY": "LOCATION",
    "ORGANIZATION": "ORGANIZATION",
    "NAT_REL_POL": "NRP",
    "DATETIME": "DATE_TIME",
    "MONEY": "MONEY",
    "NUMERIC_VALUE": "NUMBER",
    "QUANTITY": "NUMBER",
    "ORDINAL": "ORDINAL",
    "EVENT": "EVENT",
    "PRODUCT": "PRODUCT",
    "LANGUAGE": "LANGUAGE",
    "WORK_OF_ART": "WORK_OF_ART",
}


def build_analyzer() -> AnalyzerEngine:
    configuration = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "ro", "model_name": "ro_core_news_lg"}],
        "ner_model_configuration": {
            "model_to_presidio_entity_mapping": NER_LABEL_MAPPING,
            "default_score": 0.85,
        },
    }
    nlp_engine = NlpEngineProvider(nlp_configuration=configuration).create_engine()

    # GOTCHA: build the registry with supported_languages, and add SpacyRecognizer
    # explicitly. If the registry has any recognizer but no SpacyRecognizer,
    # Presidio skips the default auto-load and NER returns nothing.
    registry = RecognizerRegistry(supported_languages=["ro"])
    registry.add_recognizer(SpacyRecognizer(supported_language="ro"))
    registry.add_recognizer(EmailRecognizer(supported_language="ro"))
    registry.add_recognizer(
        PhoneRecognizer(supported_language="ro", supported_regions=["RO"],
                        context=["telefon", "tel"])
    )
    registry.add_recognizer(IbanRecognizer(supported_language="ro"))
    registry.add_recognizer(RomanianCnpRecognizer())
    registry.add_recognizer(Card16Recognizer())

    return AnalyzerEngine(nlp_engine=nlp_engine, registry=registry,
                          supported_languages=["ro"])


def anonymize_text(analyzer: AnalyzerEngine, text: str):
    """Return (anonymized_text, entities). Same source string always maps to the
    same placeholder (e.g. every occurrence of a CNP -> <CNP_RO_1>)."""
    results = analyzer.analyze(text=text, language="ro")
    entities = [
        {"text": text[r.start:r.end], "type": r.entity_type,
         "start": r.start, "end": r.end, "score": round(r.score, 2)}
        for r in results
    ]

    placeholders: dict = {}
    output = text
    for r in sorted(results, key=lambda x: -x.start):
        key = (r.entity_type, text[r.start:r.end])
        if key not in placeholders:
            n = sum(1 for v in placeholders.values() if v.startswith(f"<{r.entity_type}"))
            placeholders[key] = f"<{r.entity_type}_{n + 1}>"
        output = output[:r.start] + placeholders[key] + output[r.end:]
    return output, entities


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Anonymize Romanian text (names, CNP, phones, emails, IDs).")
    parser.add_argument("input", help="a .txt file or a folder with .txt files")
    parser.add_argument("-o", "--output", help="output file or folder (default: stdout)")
    parser.add_argument("--json", action="store_true",
                        help="also save detected entities next to the output (<name>_entities.json)")
    args = parser.parse_args()

    in_path = pathlib.Path(args.input)
    files = sorted(in_path.glob("*.txt")) if in_path.is_dir() else [in_path]
    if not files:
        sys.exit(f"No .txt file(s) found at: {in_path}")

    out_path = pathlib.Path(args.output) if args.output else None
    if out_path and len(files) > 1:
        out_path.mkdir(parents=True, exist_ok=True)

    analyzer = build_analyzer()
    print("Loading model (ro_core_news_lg)... first run takes ~30s", file=sys.stderr)

    for f in files:
        text = f.read_text(encoding="utf-8")
        anonymized, entities = anonymize_text(analyzer, text)

        if out_path is None:
            print(anonymized)
            target = None
        elif len(files) == 1:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(anonymized, encoding="utf-8")
            target = out_path
        else:  # batch mode: -o is treated as a folder
            out_path.mkdir(parents=True, exist_ok=True)
            target = out_path / f.name
            target.write_text(anonymized, encoding="utf-8")

        if args.json and target is not None:
            (target.parent / (target.stem + "_entities.json")).write_text(
                json.dumps(entities, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{f.name}] {len(entities)} entities found", file=sys.stderr)


if __name__ == "__main__":
    main()
