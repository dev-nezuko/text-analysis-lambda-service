import os
from functools import lru_cache

from src.manage_models import get_model_from_disk


@lru_cache(maxsize=1)
def get_nlp():
    import spacy

    model = os.environ['SPACY_MODEL_MEDIUM']
    return spacy.load(get_model_from_disk(model))


def find_locations(text: str) -> list[str]:
    """Return unique GPE/LOC entity text, preserving first appearance order."""
    doc = get_nlp()(text)
    return list(dict.fromkeys(entity.text for entity in doc.ents if entity.label_ in {'GPE', 'LOC'}))
