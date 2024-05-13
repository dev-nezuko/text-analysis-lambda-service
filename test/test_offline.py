import io
import tarfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import app
from src.manage_models import unzip_file, validate_model_name
from src.nlp import find_locations


def archive_at(tmp_path, name, kind=None):
    path = tmp_path / 'fixture.tar.gz'
    with tarfile.open(path, 'w:gz') as archive:
        member = tarfile.TarInfo(name)
        member.size = 4
        if kind is not None:
            member.type = kind
            member.linkname = '../outside'
        archive.addfile(member, io.BytesIO(b'demo') if kind is None else None)
    return path


def test_traversal_rejected_before_writing(tmp_path):
    path = archive_at(tmp_path, '../outside')
    with pytest.raises(ValueError):
        unzip_file(str(path), str(tmp_path / 'models'))
    assert not (tmp_path / 'outside').exists()


@pytest.mark.parametrize('kind', [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE])
def test_links_and_special_files_rejected(tmp_path, kind):
    with pytest.raises(ValueError):
        unzip_file(str(archive_at(tmp_path, 'bad', kind)), str(tmp_path / 'models'))


def test_regular_file_extracts(tmp_path):
    unzip_file(str(archive_at(tmp_path, 'model/data')), str(tmp_path / 'models'))
    assert (tmp_path / 'models/model/data').read_bytes() == b'demo'


def test_checksum_mismatch_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv('SPACY_MODEL_SHA256', '0' * 64)
    with pytest.raises(ValueError):
        unzip_file(str(archive_at(tmp_path, 'data')), str(tmp_path / 'models'))


@pytest.mark.parametrize('name', ['../escape', 'bad/model-1.2.3', None])
def test_invalid_model_name_rejected(name):
    with pytest.raises(ValueError):
        validate_model_name(name)


def test_locations_are_unique_and_preserve_appearance_order():
    entities = [('Spain', 'GPE'), ('Ada', 'PERSON'), ('UK', 'GPE'), ('Spain', 'GPE')]
    doc = SimpleNamespace(ents=[SimpleNamespace(text=text, label_=label) for text, label in entities])
    with patch('src.nlp.get_nlp', return_value=lambda text: doc):
        assert find_locations('Synthetic input') == ['Spain', 'UK']


@pytest.mark.parametrize(
    'body',
    [[], {}, {'text': 42}, {'text': ''}, {'text': 'x' * 20001}, {'text': 'example', 'extra': True}],
)
def test_invalid_requests_never_load_a_model(body):
    with patch('app.find_locations') as extract:
        assert app.test_client().post('/find_locations', json=body).status_code == 400
    extract.assert_not_called()


def test_valid_request_returns_locations_without_external_model():
    with patch('app.find_locations', return_value=['Spain']) as extract:
        response = app.test_client().post('/find_locations', json={'text': 'Synthetic Spain example'})
    assert response.json == ['Spain']
    extract.assert_called_once_with(text='Synthetic Spain example')


def test_debug_endpoint_is_not_exposed():
    assert app.test_client().get('/debug-sentry').status_code == 404
