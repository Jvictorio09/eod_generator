#!/usr/bin/env sh
# Railway Console helper — uses the same venv as the deploy when available.
set -e
cd "$(dirname "$0")"

if [ -x /opt/venv/bin/python ]; then
  PYTHON=/opt/venv/bin/python
elif [ -x .venv/bin/python ]; then
  PYTHON=.venv/bin/python
else
  PYTHON=python3
fi

exec "$PYTHON" manage.py "$@"
