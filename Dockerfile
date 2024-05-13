FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt \
    && useradd --create-home --uid 10001 appuser

COPY app.py settings.py ./
COPY src ./src

USER appuser

# blank:en serves the API without downloading anything. Pass a versioned model
# name plus S3_BUCKET (and AWS credentials) to use a real model from S3.
ENV SPACY_MODEL_MEDIUM=blank:en
EXPOSE 8000

# One worker so the model is loaded once; threads share it.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "app:app"]
