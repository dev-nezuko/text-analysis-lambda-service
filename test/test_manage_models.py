import hashlib
import io
import os
import tarfile

import boto3
import pytest
from moto import mock_aws

from src import manage_models
from src.manage_models import get_model_from_disk, unzip_file, upload_model_to_s3

MODEL = 'xx_test_model-1.0.0'
BUCKET = 'example-model-bucket'


def add_file(archive, name, data=b'{}', mode=0o644):
    member = tarfile.TarInfo(name)
    member.size = len(data)
    member.mode = mode
    archive.addfile(member, io.BytesIO(data))


def model_archive(path, extra=None):
    """A tarball with the same layout as the official spaCy model releases."""
    with tarfile.open(path, 'w:gz') as archive:
        add_file(archive, f'{MODEL}/setup.py', b'')
        add_file(archive, f'{MODEL}/xx_test_model/{MODEL}/meta.json')
        if extra:
            extra(archive)
    return path


def sha256_of(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def s3(monkeypatch):
    for key in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SECURITY_TOKEN', 'AWS_SESSION_TOKEN'):
        monkeypatch.setenv(key, 'testing')
    monkeypatch.setenv('AWS_DEFAULT_REGION', 'us-east-1')
    monkeypatch.delenv('AWS_PROFILE', raising=False)
    monkeypatch.setenv('S3_BUCKET', BUCKET)
    with mock_aws():
        client = boto3.client('s3')
        client.create_bucket(Bucket=BUCKET)
        yield client


def publish(s3, archive_path):
    s3.upload_file(str(archive_path), BUCKET, f'models/{MODEL}.tar.gz')


def test_model_is_fetched_from_s3_and_archive_removed(tmp_path, s3):
    publish(s3, model_archive(tmp_path / 'upload.tar.gz'))
    cache = tmp_path / 'cache'

    path = get_model_from_disk(MODEL, dest=str(cache))

    assert path == str(cache / MODEL / 'xx_test_model' / MODEL)
    assert (cache / MODEL / 'xx_test_model' / MODEL / 'meta.json').exists()
    assert sorted(os.listdir(cache)) == [MODEL]


def test_cached_model_skips_s3(tmp_path, monkeypatch):
    (tmp_path / MODEL / 'xx_test_model' / MODEL).mkdir(parents=True)
    monkeypatch.setattr(manage_models, 'download_model_from_s3', pytest.fail)
    assert get_model_from_disk(MODEL, dest=str(tmp_path)).endswith(f'xx_test_model/{MODEL}')


def test_matching_checksum_is_accepted_in_any_case_and_with_whitespace(tmp_path, s3, monkeypatch):
    archive = model_archive(tmp_path / 'upload.tar.gz')
    publish(s3, archive)
    monkeypatch.setenv('SPACY_MODEL_SHA256', f'  {sha256_of(archive).upper()}\n')
    assert os.path.isdir(get_model_from_disk(MODEL, dest=str(tmp_path / 'cache')))


def test_checksum_mismatch_leaves_no_model_behind(tmp_path, s3, monkeypatch):
    publish(s3, model_archive(tmp_path / 'upload.tar.gz'))
    monkeypatch.setenv('SPACY_MODEL_SHA256', 'a' * 64)
    cache = tmp_path / 'cache'
    with pytest.raises(ValueError, match='checksum'):
        get_model_from_disk(MODEL, dest=str(cache))
    assert os.listdir(cache) == []


def test_malformed_checksum_setting_is_rejected(tmp_path, s3, monkeypatch):
    publish(s3, model_archive(tmp_path / 'upload.tar.gz'))
    monkeypatch.setenv('SPACY_MODEL_SHA256', 'not-a-sha')
    with pytest.raises(ValueError, match='64 hexadecimal'):
        get_model_from_disk(MODEL, dest=str(tmp_path / 'cache'))


def test_failed_extraction_does_not_poison_the_cache(tmp_path, s3):
    def bad_member(archive):
        add_file(archive, '../escape.txt', b'x')

    publish(s3, model_archive(tmp_path / 'bad.tar.gz', extra=bad_member))
    cache = tmp_path / 'cache'
    with pytest.raises(ValueError):
        get_model_from_disk(MODEL, dest=str(cache))
    assert os.listdir(cache) == []
    assert not (tmp_path / 'escape.txt').exists()

    publish(s3, model_archive(tmp_path / 'good.tar.gz'))
    assert os.path.isdir(get_model_from_disk(MODEL, dest=str(cache)))


def test_archive_without_model_directory_is_rejected(tmp_path, s3):
    path = tmp_path / 'flat.tar.gz'
    with tarfile.open(path, 'w:gz') as archive:
        add_file(archive, 'meta.json')
    publish(s3, path)
    with pytest.raises(ValueError, match='top-level'):
        get_model_from_disk(MODEL, dest=str(tmp_path / 'cache'))


def test_missing_bucket_setting_is_reported(tmp_path, monkeypatch):
    monkeypatch.delenv('S3_BUCKET', raising=False)
    with pytest.raises(ValueError, match='S3_BUCKET'):
        get_model_from_disk(MODEL, dest=str(tmp_path))


def test_extraction_strips_setuid_bits(tmp_path):
    def setuid_file(archive):
        add_file(archive, f'{MODEL}/tool', b'#!/bin/sh\n', mode=0o4755)

    unzip_file(str(model_archive(tmp_path / 'm.tar.gz', extra=setuid_file)), str(tmp_path / 'out'))
    assert not os.stat(tmp_path / 'out' / MODEL / 'tool').st_mode & 0o4000


def test_upload_verifies_local_archive_before_sending(tmp_path, s3, monkeypatch):
    archive = model_archive(tmp_path / f'{MODEL}.tar.gz')
    monkeypatch.setenv('SPACY_MODEL_SHA256', 'b' * 64)
    with pytest.raises(ValueError, match='checksum'):
        upload_model_to_s3(MODEL, location=str(tmp_path))
    assert s3.list_objects_v2(Bucket=BUCKET).get('KeyCount') == 0

    monkeypatch.setenv('SPACY_MODEL_SHA256', sha256_of(archive))
    upload_model_to_s3(MODEL, location=str(tmp_path))
    assert s3.head_object(Bucket=BUCKET, Key=f'models/{MODEL}.tar.gz')['ContentLength'] > 0
