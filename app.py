import os
from flask import Flask, jsonify, request
import settings
from src.nlp import find_locations

if os.getenv('SENTRY_DSN'):
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    sentry_sdk.init(dsn=os.environ['SENTRY_DSN'], integrations=[FlaskIntegration()], send_default_pii=False)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 128 * 1024

@app.route('/')
def index():
    return jsonify({'service': 'location extraction', 'endpoint': 'POST /find_locations'})

@app.route('/find_locations', methods=['POST'])
def route_find_locations():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {'text'} or not isinstance(payload.get('text'), str):
        return jsonify({'error': 'Provide one JSON string field named text.'}), 400
    if not payload['text'].strip() or len(payload['text']) > 20000:
        return jsonify({'error': 'text must contain 1 to 20000 characters.'}), 400
    return jsonify(find_locations(text=payload['text']))
