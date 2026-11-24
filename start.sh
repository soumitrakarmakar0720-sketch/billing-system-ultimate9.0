#!/bin/sh
set -eu
flask --app app upgrade-enterprise
exec gunicorn app:app --bind "0.0.0.0:${PORT:-10000}" --workers 2 --threads 4
