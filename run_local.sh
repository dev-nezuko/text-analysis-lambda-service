#!/bin/sh
# Development server on http://127.0.0.1:5001 (reads .env through settings.py).
exec flask --app app run --port 5001
