#!/bin/sh

set -e

# Really simple benchmarking script comparing current code to a
# specific previous version.
VERSION=$1
if [ ! "$VERSION" ]; then
    >&2 echo "Usage: $0 VERSION"
    exit 1
fi

VENV="$(dirname $0)/.venv"
if [ ! -e "$VENV/bin/activate" ]; then
    python -m venv "$VENV"
fi
echo Current:
hatch -e benchmark-mypyc run python text.py
hatch -e benchmark-mypyc run python objects.py
hatch -e benchmark-mypyc run python structure.py
. "$VENV/bin/activate"
for VERSION in "$@"; do
    echo Version $VERSION:
    pip -q install playa-pdf==$VERSION
    python text.py
    python objects.py
    python structure.py
done
