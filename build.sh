#!/usr/bin/env bash
# Render build step. Fails the deploy on any error.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
