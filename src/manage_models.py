import argparse
import hashlib
import os
import re
import tarfile
from pathlib import Path

import boto3
import requests

import settings  # noqa: F401  (loads .env before the module-level lookups below)

model = os.getenv('SPACY_MODEL_MEDIUM')
model_sm = os.getenv('SPACY_MODEL_SMALL')
dest = '/tmp/models'
s3_bucket = os.getenv('S3_BUCKET')


def makedir_if_not_exists(dest):
    if not os.path.exists(dest):
        os.makedirs(dest)


def validate_model_name(model):
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9_]+-[0-9]+\.[0-9]+\.[0-9]+', model):
        raise ValueError('Use a versioned spaCy model name without path components.')


def download_model_from_github(model: str, dest: str = '/tmp/models') -> str:
    validate_model_name(model)
    print(f'Downloading {model} to {dest}')
    url = f'https://github.com/explosion/spacy-models/releases/download/{model}/{model}.tar.gz'

    makedir_if_not_exists(dest)
    filename = os.path.join(Path(dest), f'{model}.tar.gz')

    # download model
    with requests.get(url, stream=True, timeout=(10, 60)) as r:
        r.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    unzip_file(filename, dest)
    uncompressed_file = os.path.join(Path(dest), model)
    print(f'Downloaded to {uncompressed_file}')

    return uncompressed_file


def download_model_from_s3(model: str, dest: str) -> str:
    validate_model_name(model)
    if not s3_bucket:
        raise ValueError('Configure S3_BUCKET before downloading a model.')
    print(f'Downloading {model} from S3')
    makedir_if_not_exists(dest)
    filename = os.path.join(Path(dest), f'{model}.tar.gz')

    # download model
    object_name = f'models/{model}.tar.gz'
    s3 = boto3.client('s3')
    s3.download_file(s3_bucket, object_name, filename)

    unzip_file(filename, dest)
    uncompressed_file = os.path.join(Path(dest), model)
    print(f'Downloaded to {uncompressed_file}')

    return uncompressed_file


def unzip_file(filename: str, dest: str):
    """Reject traversal, links, special files and unbounded archive expansion."""
    expected = os.getenv('SPACY_MODEL_SHA256')
    if expected:
        digest = hashlib.sha256()
        with open(filename, 'rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
        if digest.hexdigest().lower() != expected.lower():
            raise ValueError('Model archive checksum mismatch.')
    root = Path(dest).resolve()
    with tarfile.open(filename) as archive:
        members = archive.getmembers()
        if len(members) > 10000 or sum(item.size for item in members) > 1024**3:
            raise ValueError('Model archive exceeds extraction limits.')
        for member in members:
            if Path(member.name).is_absolute() or '..' in Path(member.name).parts:
                raise ValueError('Archive paths must stay relative to the model directory.')
            target = (root / member.name).resolve()
            if root != target and root not in target.parents:
                raise ValueError('Archive path escapes the model directory.')
            if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                raise ValueError('Only regular model files and directories are permitted.')
        archive.extractall(path=root, members=members)


def get_model_from_disk(model: str, dest: str = dest) -> str:
    validate_model_name(model)
    print(f'Getting model {model} from disk')
    filename = os.path.join(Path(dest), model)
    if not os.path.exists(filename):
        print('Not in disk, downloading from S3 bucket')
        filename = download_model_from_s3(model, dest)
    dirname = model.split('-')[0]
    model_full_path = os.path.join(filename, dirname, model)
    return model_full_path


def upload_model_to_s3(model: str, location: str = dest, s3_bucket: str = s3_bucket):
    validate_model_name(model)
    if not s3_bucket:
        raise ValueError('Configure S3_BUCKET before uploading a model.')
    print(f'Uploading {model} from {location} to {s3_bucket} S3 bucket')
    file_full_path = os.path.join(Path(location), f'{model}.tar.gz')
    if not os.path.exists(file_full_path):
        print('File not in disk, downloading from GitHub')
        download_model_from_github(model, dest=location)
    s3_client = boto3.client('s3')
    s3_client.upload_file(file_full_path, s3_bucket, f'models/{model}.tar.gz')
    print('Done')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Download Spacy models to disk and upload them to S3')
    parser.add_argument('--download', '-d', action='store_true')
    parser.add_argument('--upload', '-u', action='store_true')

    args = parser.parse_args()

    if args.download:
        download_model_from_github(model=model_sm)
    if args.upload:
        upload_model_to_s3(model=model_sm)

    # download_model_from_github(model=model)
    # get_model_from_disk(model_sm, dest=f'{dest}/test_S3')
