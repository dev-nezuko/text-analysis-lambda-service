from unittest.mock import patch

import pytest

from app import MAX_TEXT_CHARS, app
from src.nlp import ModelUnavailable


@pytest.fixture
def client():
    return app.test_client()


def test_unknown_route_returns_json_404(client):
    response = client.get('/nope')
    assert response.status_code == 404
    assert response.is_json and 'error' in response.json


def test_wrong_method_returns_json_405(client):
    response = client.get('/find_locations')
    assert response.status_code == 405
    assert response.is_json and 'error' in response.json


def test_oversized_body_returns_json_413_without_loading_model(client):
    with patch('app.find_locations') as extract:
        response = client.post('/find_locations', json={'text': 'x' * (130 * 1024)})
    assert response.status_code == 413
    assert response.is_json
    extract.assert_not_called()


def test_longest_allowed_text_is_accepted(client):
    with patch('app.find_locations', return_value=[]) as extract:
        response = client.post('/find_locations', json={'text': 'x' * MAX_TEXT_CHARS})
    assert response.status_code == 200
    extract.assert_called_once()


def test_non_json_body_is_rejected(client):
    response = client.post('/find_locations', data='text=Spain', content_type='text/plain')
    assert response.status_code == 400
    assert response.json == {'error': 'Provide one JSON string field named text.'}


def test_model_failure_returns_503_without_internal_detail(client):
    with patch('app.find_locations', side_effect=ModelUnavailable('bucket secret-bucket: AccessDenied')):
        response = client.post('/find_locations', json={'text': 'Spain'})
    assert response.status_code == 503
    assert 'secret-bucket' not in response.get_data(as_text=True)


def test_unexpected_error_returns_json_500_without_internal_detail(client):
    with patch('app.find_locations', side_effect=RuntimeError('stack detail')):
        response = client.post('/find_locations', json={'text': 'Spain'})
    assert response.status_code == 500
    assert response.is_json
    assert 'stack detail' not in response.get_data(as_text=True)
