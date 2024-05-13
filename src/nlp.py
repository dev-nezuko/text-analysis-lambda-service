import os
import threading

from botocore.exceptions import BotoCoreError, ClientError

from src.manage_models import get_model_from_disk

LOCATION_LABELS = {'GPE', 'LOC'}

_nlp = None
_nlp_lock = threading.Lock()


class ModelUnavailable(RuntimeError):
    """The configured spaCy model could not be fetched or loaded."""


def load_configured_model():
    import spacy

    model = os.getenv('SPACY_MODEL_MEDIUM', '').strip()
    if not model:
        raise ModelUnavailable('SPACY_MODEL_MEDIUM is not set.')
    if model.startswith('blank:'):
        # Tokenizer-only pipeline for local smoke tests: no download, and no entities.
        return spacy.blank(model.removeprefix('blank:'))
    try:
        return spacy.load(get_model_from_disk(model))
    except (ValueError, OSError, BotoCoreError, ClientError) as error:
        raise ModelUnavailable(f'Could not load {model}: {error}') from error


def get_nlp():
    """Load the model once per process.

    The lock matters on cold start: without it, concurrent first requests each
    download and load their own copy, multiplying memory and /tmp use.
    """
    global _nlp
    if _nlp is None:
        with _nlp_lock:
            if _nlp is None:
                _nlp = load_configured_model()
    return _nlp


def find_locations(text: str) -> list[str]:
    """Return unique GPE/LOC entity text, preserving first appearance order."""
    doc = get_nlp()(text)
    return list(dict.fromkeys(entity.text for entity in doc.ents if entity.label_ in LOCATION_LABELS))
