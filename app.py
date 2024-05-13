import os

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

import settings  # noqa: F401  (loads .env before anything reads os.environ)
from src.nlp import ModelUnavailable, find_locations

if os.getenv('SENTRY_DSN'):
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration

    sentry_sdk.init(dsn=os.environ['SENTRY_DSN'], integrations=[FlaskIntegration()], send_default_pii=False)

MAX_TEXT_CHARS = 20000

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 128 * 1024


@app.errorhandler(HTTPException)
def http_error_as_json(error):
    # Unhandled exceptions reach this as a 500 after Flask has logged them and
    # signalled Sentry, so the original error text never goes to the client.
    return jsonify({'error': error.description}), error.code


@app.errorhandler(ModelUnavailable)
def model_unavailable(error):
    app.logger.error('Model unavailable: %s', error)
    return jsonify({'error': 'The language model is not available. Try again later.'}), 503


@app.route('/')
def index():
    return jsonify({'service': 'location extraction', 'endpoint': 'POST /find_locations'})


@app.route('/find_locations', methods=['POST'])
def route_find_locations():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {'text'} or not isinstance(payload.get('text'), str):
        return jsonify({'error': 'Provide one JSON string field named text.'}), 400
    if not payload['text'].strip() or len(payload['text']) > MAX_TEXT_CHARS:
        return jsonify({'error': f'text must contain 1 to {MAX_TEXT_CHARS} characters.'}), 400
    return jsonify(find_locations(text=payload['text']))
