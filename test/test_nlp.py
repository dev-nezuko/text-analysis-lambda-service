import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
import spacy

from src import nlp as nlp_module
from src.nlp import find_locations


def blank_pipeline_with_place_patterns():
    nlp = spacy.blank('en')
    ruler = nlp.add_pipe('entity_ruler')
    ruler.add_patterns(
        [
            {'label': 'GPE', 'pattern': 'Spain'},
            {'label': 'GPE', 'pattern': 'UK'},
            {'label': 'LOC', 'pattern': [{'LOWER': 'lake'}, {'LOWER': 'como'}]},
            {'label': 'PERSON', 'pattern': 'Ada'},
        ]
    )
    return nlp


def test_find_locations_with_a_real_spacy_pipeline():
    nlp = blank_pipeline_with_place_patterns()
    with patch('src.nlp.get_nlp', return_value=nlp):
        locations = find_locations(text='Ada says Spain is sunnier than the UK, and Spain beats Lake Como')
    assert locations == ['Spain', 'UK', 'Lake Como']


@pytest.fixture
def fresh_model_cache(monkeypatch):
    monkeypatch.setattr(nlp_module, '_nlp', None)


def test_concurrent_cold_start_loads_the_model_once(fresh_model_cache, monkeypatch):
    calls = []
    start = threading.Barrier(8)

    def slow_load():
        calls.append(1)
        time.sleep(0.2)
        return spacy.blank('en')

    monkeypatch.setattr(nlp_module, 'load_configured_model', slow_load)

    def first_request():
        start.wait()
        return nlp_module.get_nlp()

    with ThreadPoolExecutor(max_workers=8) as pool:
        pipelines = list(pool.map(lambda _: first_request(), range(8)))

    assert len(calls) == 1
    assert all(pipeline is pipelines[0] for pipeline in pipelines)


def test_failed_load_is_retried_on_the_next_request(fresh_model_cache, monkeypatch):
    outcomes = iter([nlp_module.ModelUnavailable('S3 timed out'), spacy.blank('en')])

    def flaky_load():
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(nlp_module, 'load_configured_model', flaky_load)
    with pytest.raises(nlp_module.ModelUnavailable):
        nlp_module.get_nlp()
    assert nlp_module.get_nlp() is not None


def test_missing_model_setting_is_reported(fresh_model_cache, monkeypatch):
    monkeypatch.delenv('SPACY_MODEL_MEDIUM', raising=False)
    with pytest.raises(nlp_module.ModelUnavailable, match='SPACY_MODEL_MEDIUM'):
        nlp_module.get_nlp()


def test_unreachable_model_store_is_reported(fresh_model_cache, monkeypatch):
    monkeypatch.setenv('SPACY_MODEL_MEDIUM', 'xx_missing-1.0.0')
    monkeypatch.delenv('S3_BUCKET', raising=False)
    with pytest.raises(nlp_module.ModelUnavailable, match='S3_BUCKET'):
        nlp_module.get_nlp()


def test_blank_pipeline_runs_without_any_download(fresh_model_cache, monkeypatch):
    monkeypatch.setenv('SPACY_MODEL_MEDIUM', 'blank:en')
    monkeypatch.setattr('src.nlp.get_model_from_disk', pytest.fail)
    assert find_locations('Spain is sunnier than the UK') == []
