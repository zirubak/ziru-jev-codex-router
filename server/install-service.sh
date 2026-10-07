#!/bin/sh
# Install Jev through the root transaction so failed migrations can be restored.
set -eu
REPO="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
JEV_PYTHON="${JEV_PYTHON:-$(command -v python3)}"
export JEV_PYTHON
"$JEV_PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || {
  echo "Python 3.11 or newer is required" >&2
  exit 1
}
exec "$JEV_PYTHON" "$REPO/server/install_service.py"
