import argparse
import hashlib
import os
import re
import shutil
import tarfile
import tempfile
from pathlib import Path

import boto3
import requests

import settings  # noqa: F401  (loads .env before the lookups below)

dest = '/tmp/models'
MAX_ARCHIVE_MEMBERS = 10000
MAX_EXPANDED_BYTES = 1024**3


def validate_model_name(model):
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9_]+-[0-9]+\.[0-9]+\.[0-9]+', model):
        raise ValueError('Use a versioned spaCy model name without path components.')


def expected_sha256() -> str | None:
    value = (os.getenv('SPACY_MODEL_SHA256') or '').strip().lower()
    if not value:
        return None
    if not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('SPACY_MODEL_SHA256 must be 64 hexadecimal characters.')
    return value


def verify_checksum(filename: str):
    expected = expected_sha256()
    if expected is None:
        return
    digest = hashlib.sha256()
    with open(filename, 'rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    if digest.hexdigest() != expected:
        raise ValueError('Model archive checksum mismatch.')


def unzip_file(filename: str, dest: str):
    """Verify the checksum, then extract only regular files and directories inside dest."""
    verify_checksum(filename)
    root = Path(dest).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(filename) as archive:
        members = archive.getmembers()
        if len(members) > MAX_ARCHIVE_MEMBERS or sum(item.size for item in members) > MAX_EXPANDED_BYTES:
            raise ValueError('Model archive exceeds extraction limits.')
        for member in members:
            if Path(member.name).is_absolute() or '..' in Path(member.name).parts:
                raise ValueError('Archive paths must stay relative to the model directory.')
            if not (member.isfile() or member.isdir()):
                raise ValueError('Only regular model files and directories are permitted.')
        # The checks above give clear errors; the data filter is the stdlib's own backstop
        # (it also strips setuid bits and other unsafe metadata).
        archive.extractall(path=root, members=members, filter='data')


def install_archive(filename: str, model: str, dest: str) -> str:
    """Extract into a private staging dir and publish it with one rename.

    A failed or interrupted extraction therefore never leaves a half-written
    model directory that a later request would treat as a valid cache.
    """
    final_dir = Path(dest) / model
    staging = Path(tempfile.mkdtemp(prefix=f'.{model}-', dir=dest))
    try:
        unzip_file(filename, str(staging))
        extracted = staging / model
        if not extracted.is_dir():
            raise ValueError(f'Archive does not contain a top-level {model}/ directory.')
        try:
            os.rename(extracted, final_dir)
        except OSError:
            # Another worker published the same model first; keep theirs.
            if not final_dir.is_dir():
                raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return str(final_dir)


def temporary_download_path(model: str, dest: str) -> str:
    Path(dest).mkdir(parents=True, exist_ok=True)
    handle, path = tempfile.mkstemp(prefix=f'.{model}-', suffix='.tar.gz.part', dir=dest)
    os.close(handle)
    return path


def download_model_from_github(model: str, dest: str = dest) -> str:
    """Download the official release archive to dest/<model>.tar.gz and unpack it."""
    validate_model_name(model)
    print(f'Downloading {model} to {dest}')
    url = f'https://github.com/explosion/spacy-models/releases/download/{model}/{model}.tar.gz'
    partial = temporary_download_path(model, dest)
    try:
        with requests.get(url, stream=True, timeout=(10, 60)) as response:
            response.raise_for_status()
            with open(partial, 'wb') as target:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    target.write(chunk)
        verify_checksum(partial)
        archive = os.path.join(dest, f'{model}.tar.gz')
        os.replace(partial, archive)
    finally:
        if os.path.exists(partial):
            os.remove(partial)
    return install_archive(archive, model, dest)


def download_model_from_s3(model: str, dest: str) -> str:
    """Fetch models/<model>.tar.gz from S3_BUCKET, unpack it and drop the archive."""
    validate_model_name(model)
    bucket = os.getenv('S3_BUCKET')
    if not bucket:
        raise ValueError('Configure S3_BUCKET before downloading a model.')
    print(f'Downloading {model} from S3')
    partial = temporary_download_path(model, dest)
    try:
        boto3.client('s3').download_file(bucket, f'models/{model}.tar.gz', partial)
        # Lambda's /tmp is small, so the archive is removed once the model is unpacked.
        return install_archive(partial, model, dest)
    finally:
        os.remove(partial)


def get_model_from_disk(model: str, dest: str = dest) -> str:
    validate_model_name(model)
    model_dir = os.path.join(dest, model)
    if not os.path.isdir(model_dir):
        print(f'{model} is not cached in {dest}, downloading from S3')
        model_dir = download_model_from_s3(model, dest)
    package = model.split('-')[0]
    model_path = os.path.join(model_dir, package, model)
    if not os.path.isdir(model_path):
        raise ValueError(f'Expected the spaCy package layout {model}/{package}/{model} in the archive.')
    return model_path


def upload_model_to_s3(model: str, location: str = dest, s3_bucket: str | None = None):
    validate_model_name(model)
    bucket = s3_bucket or os.getenv('S3_BUCKET')
    if not bucket:
        raise ValueError('Configure S3_BUCKET before uploading a model.')
    archive = os.path.join(location, f'{model}.tar.gz')
    if not os.path.exists(archive):
        print('Archive not on disk, downloading from GitHub')
        download_model_from_github(model, dest=location)
    verify_checksum(archive)
    print(f'Uploading {model} from {location} to {bucket}')
    boto3.client('s3').upload_file(archive, bucket, f'models/{model}.tar.gz')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Download spaCy models to disk and upload them to S3')
    parser.add_argument('--download', '-d', action='store_true')
    parser.add_argument('--upload', '-u', action='store_true')
    args = parser.parse_args()

    small_model = os.getenv('SPACY_MODEL_SMALL')
    if args.download:
        download_model_from_github(model=small_model)
    if args.upload:
        upload_model_to_s3(model=small_model)
