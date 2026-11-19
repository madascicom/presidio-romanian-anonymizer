# Romanian anonymization with Presidio — names, CNP, phones, emails, IDs (free, local, offline)

De-identification of Romanian medical / administrative text, built on
[Microsoft Presidio](https://github.com/microsoft/presidio) (MIT) + spaCy's
Romanian model + two custom recognizers. **Everything runs locally on CPU —
no API keys, no cloud, no per-document limits.**

**În română (TL;DR):** scriptul anonimizează text medical/administrativ românesc
peste tot local: nume, CNP (cu validare reală a sumei de control), telefoane în
toate formatele RO, e-mailuri, carduri — $0, licență MIT. Testat pe documente
mock medicale: **0 scurgeri de identificatori**. Vezi secțiunea „Romanian notes”.

## What it detects

| Entity type | How |
|---|---|
| Person names, locations, hospitals, dates | spaCy `ro_core_news_lg` via Presidio's `SpacyRecognizer` |
| **CNP** (Romanian personal numeric code) | custom recognizer with **full checksum validation** — 13-digit numbers that fail the official checksum are *not* flagged |
| Phones (RO): `+40 …`, `07xx …`, `02xx/03xx …`, dotted formats | Presidio `PhoneRecognizer` with `supported_regions=["RO"]` (phonenumbers library) |
| Emails, IBANs | Presidio predefined recognizers |
| 16-digit grouped numbers (health-card style) | custom recognizer |

Placeholders are consistent: the same source string always maps to the same
placeholder (`<CNP_RO_1>`, `<PERSON_2>`), so pseudonymized documents stay
linkable for downstream NLP.

## Tested results (Romanian mock medical documents)

Against a ground-truth list of planted entities (3 discharge/referral/consult
documents, fictional data): **0 CNPs, 0 phone numbers, 0 emails leaked**,
100% of name tokens covered. Known gaps: insurance-file numbers like `FA 08/452311`
(add one regex recognizer — snippet below) and an occasional false positive on
drug names inherited from the spaCy model.

## Quick start

```bash
pip install "presidio-analyzer>=2.2.356" "spacy>=3.7,<4"
python -m spacy download ro_core_news_lg

# single file (prints anonymized text)
python presidio_ro_anonymizer.py examples/03_consult_ambulatoriu.txt

# save to file + entity dump
python presidio_ro_anonymizer.py document.txt -o anonymized.txt --json

# batch a folder
python presidio_ro_anonymizer.py examples/ -o out/
```

## The gotcha worth knowing

If you build your own `RecognizerRegistry` in Presidio and add recognizers to it,
Presidio skips its default auto-load — and that auto-load is what registers the
`SpacyRecognizer` that runs your NER model. Symptom: regex recognizers work,
NER silently returns nothing. Fix (already applied here):

```python
registry = RecognizerRegistry(supported_languages=["ro"])
registry.add_recognizer(SpacyRecognizer(supported_language="ro"))  # <- without this, no NER
```

## Adding your own recognizers

```python
class InsuranceFileRecognizer(PatternRecognizer):
    PATTERNS = [Pattern("fisa-asigurat", r"\bFA \d{2}/\d{6}\b", 0.4)]
    CONTEXT = ["fișă", "asigurat"]
    def __init__(self, **kwargs):
        super().__init__(supported_entity="RO_INSURANCE_FILE", supported_language="ro",
                         patterns=self.PATTERNS, context=self.CONTEXT, **kwargs)

registry.add_recognizer(InsuranceFileRecognizer())
```

## Evaluation on the included examples

```bash
python evaluate.py   # anonymizes examples/ and scores leaks vs. planted entities
```

Expected output: all identifier categories at 0 leaks; 100% name-token coverage.
The example documents contain **only fictional data** (fictional names, valid-format
CNPs generated for testing, invented institutions).

## Romanian notes (În română)

- Totul rulează **local și offline** pe CPU — potrivit pentru date sensibile
  (documentele nu părăsesc calculatorul).
- Instalare: `pip install -r requirements.txt` apoi `python -m spacy download ro_core_news_lg`.
- Limitări cunoscute: numerele de fișă de asigurat (`FA …`) nu sunt acoperite
  implicit (snippet mai sus); fals-pozitiv ocazional pe denumiri de medicamente
  (moștenit de la modelul spaCy); verificare umană recomandată înainte de publicare.
- Disclaimer: anonimizarea automată **nu garantează** conformitatea GDPR de una
  singură — folosiți-o ca pas de reducere a riscului + revizuire umană.

## License

MIT — see [LICENSE](LICENSE). Presidio and spaCy remain under their own licenses.
