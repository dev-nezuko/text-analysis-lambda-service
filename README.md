# Location extraction with S3-hosted spaCy models

A small Flask API that returns place names from text using spaCy's `GPE` and `LOC` entities. Model archives live in S3 and are cached under `/tmp/models` rather than included in the application deployment bundle.

The useful design tradeoff is smaller deployment packaging at the cost of model downloads, temporary-disk use and cold-start latency. Moving a model to S3 does not remove Lambda memory, storage or execution-time constraints.

## API contract

```http
POST /find_locations
Content-Type: application/json

{"text":"Spain is a sunnier country than the UK"}
```

An illustrative model response is `["Spain", "UK"]`. Exact recognition depends on the chosen model. Results are unique entity strings in first-appearance order, not frequency ranking, geocoded coordinates or normalized place IDs.

The endpoint accepts exactly one string field, `text`, with 1–20,000 characters. Invalid payloads return 400; request bodies larger than 128 KiB return 413. This service has no application authentication, rate limiting or per-user quota; keep it local until those controls are added.

## Start locally

The existing Pipfile targets Python 3.8 and the example model names belong to spaCy 2.3. The lockfile is a legacy environment, not a claim that a fresh current spaCy release can load those models. Review runtime/model compatibility before installation or deployment.

For an intentionally provisioned compatible environment:

```sh
pipenv sync --dev
cp .env.example .env
# Configure S3_BUCKET and a compatible versioned SPACY_MODEL_MEDIUM.
pipenv run flask --app app run --port 5001
```

The root endpoint describes the API without loading a model. The first extraction request downloads the configured model from `models/<model-name>.tar.gz` in your S3 bucket if it is not cached, then loads it into memory. Subsequent requests in that process reuse the loaded model. Warm Lambda instances may retain their own cache; separate instances do not share it.

Only use trusted model artifacts. Configure `SPACY_MODEL_SHA256` with the independently verified archive hash when appropriate. A checksum supplied alongside an untrusted replacement is not an independent trust guarantee. Archive checks reject path traversal, absolute paths, links, special files, more than 10,000 entries and more than 1 GiB of declared expanded data. They do not make arbitrary spaCy models safe to load or bound all download/cold-start costs.

`SENTRY_DSN` is optional. Error reporting disables default PII collection, but that is not a guarantee that every diagnostic is free of sensitive text. Do not use private documents as demonstration inputs. The deliberate-crash debug endpoint has been removed.

## Preparing model storage

`src/manage_models.py` has helpers to download versioned archives from the official `explosion/spacy-models` GitHub releases and upload them to your bucket. The command-line `--download` and `--upload` options use `SPACY_MODEL_SMALL`; the API uses `SPACY_MODEL_MEDIUM`. Set both deliberately if using both paths. This helper does not provision a bucket, IAM permissions or encryption policy.

S3 access uses boto3's normal credential chain. Keep credentials outside Git. Use a private bucket and restrict the application role to the required model objects. No AWS deployment or storage changes were made during this review.

## Verification

```sh
python -m pytest test/test_offline.py
```

The offline suite checks request validation, entity order/deduplication with a fake document, archive traversal/link rejection, checksum mismatch, normal extraction and absence of the debug route. It does not download a model or call AWS. The separate original `test/test_nlp.py` requires a real compatible model and can trigger the configured download; run it only after preparing that environment.

The focused checks were run on Python 3.11 with Flask 3.1, separately from the old lockfile. The declared Python 3.8/spaCy/Zappa environment and live model recognition were not verified.

## Deployment files and remaining work

`zappa_settings.json` is a Zappa example with `slim_handler`; `serverless.yml` is an alternative Serverless Framework example. Both retain Python 3.8 and original example service/bucket/account names. They are not a current, account-specific deployment plan. Select one deployment path, review its supported runtime and compatible model package, replace example ownership/configuration, and verify IAM and resource limits before deploying.

Next engineering work would add authenticated requests and quotas, model-artifact provenance, bounded downloads, concurrent cold-start coordination and a real-model regression fixture. The repository includes an MIT license whose copyright fields are still placeholders.
