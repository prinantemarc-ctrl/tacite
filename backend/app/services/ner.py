"""Local NER via spaCy.

Un modèle par langue quand il existe, sinon le modèle multilingue `xx_ent_wiki_sm`
(entraîné sur WikiNER, ~40 langues) — jamais le français par défaut : sur un texte
arabe ou chinois, le modèle français ne produit que du bruit.
"""

import logging

log = logging.getLogger("tacite.ner")

LANGUAGE_MODELS = {
    "fr": "fr_core_news_md",
    "en": "en_core_web_md",
    "de": "de_core_news_md",
    "es": "es_core_news_md",
    "it": "it_core_news_md",
    "nl": "nl_core_news_md",
    "pt": "pt_core_news_md",
    # Modèles optionnels : installés à la demande via `python -m spacy download <nom>`
    "ru": "ru_core_news_md", "pl": "pl_core_news_md", "ro": "ro_core_news_md",
    "el": "el_core_news_md", "sv": "sv_core_news_md", "da": "da_core_news_md",
    "nb": "nb_core_news_md", "no": "nb_core_news_md", "fi": "fi_core_news_md",
    "ca": "ca_core_news_md", "hr": "hr_core_news_md", "lt": "lt_core_news_md",
    "uk": "uk_core_news_md", "zh": "zh_core_web_md", "ja": "ja_core_news_md", "ko": "ko_core_news_md",
}
MULTILINGUAL = "xx_ent_wiki_sm"

_cache: dict[str, object] = {}


def _load(model_name: str):
    if model_name in _cache:
        return _cache[model_name]
    import spacy
    try:
        nlp = spacy.load(model_name, disable=["parser", "lemmatizer", "tagger", "attribute_ruler", "morphologizer"])
    except OSError:
        nlp = None
    _cache[model_name] = nlp
    return nlp


def _get_nlp(lang: str = "fr"):
    """Model for the language, else multilingual fallback, else None."""
    lang = (lang or "")[:2].lower()
    model_name = LANGUAGE_MODELS.get(lang)
    if model_name:
        nlp = _load(model_name)
        if nlp is not None:
            return nlp
        log.debug("spaCy model %s missing for %s — multilingual fallback", model_name, lang)
    nlp = _load(MULTILINGUAL)
    if nlp is None and "warned" not in _cache:
        _cache["warned"] = True
        log.error("No spaCy NER model available (not even %s) — NER disabled", MULTILINGUAL)
    return nlp


LABEL_MAP = {
    "PER": "people", "PERSON": "people",
    "ORG": "organizations",
    "LOC": "locations", "GPE": "locations",
}


def extract_entities(text: str, language: str = "fr") -> dict:
    nlp = _get_nlp(language)
    out: dict[str, list[str]] = {"people": [], "organizations": [], "locations": []}
    if nlp is None or not text:
        return out
    doc = nlp(text[:20000])
    for ent in doc.ents:
        bucket = LABEL_MAP.get(ent.label_)
        if bucket and ent.text.strip():
            out[bucket].append(ent.text.strip())
    for k in out:
        out[k] = sorted(set(out[k]))
    return out


def merge_entities(llm_entities: dict | None, ner_entities: dict) -> dict:
    merged: dict[str, list[str]] = {"people": [], "organizations": [], "locations": []}
    for k in merged:
        vals = set(ner_entities.get(k, []))
        if llm_entities:
            vals |= set(llm_entities.get(k, []))
        merged[k] = sorted(vals)
    return merged
