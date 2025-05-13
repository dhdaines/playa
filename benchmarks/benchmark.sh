#!/bin/sh

set -e

# Really simple benchmarking script comparing current code to a
# specific previous version.
VERSION=$1
if [ ! "$VERSION" ]; then
    >&2 echo "Usage: $0 VERSION"
fi

VENV="$(dirname $0)/.venv"
if [ ! -e "$VENV" ]; then
    python -m venv "$VENV"
fi
echo Current:
hatch run python text.py
hatch run python objects.py
for VERSION in "$@"; do
    echo Version $VERSION:
    (. "$VENV/bin/activate"
     pip -q install playa-pdf==$VERSION
     python text.py
     python objects.py)
done
