"""
Test basic opening and navigation of PDF documents.
"""

from pathlib import Path

import pytest

import playa

TESTDIR = Path(__file__).parent.parent / "samples"
ALLPDFS = TESTDIR.glob("**/*.pdf")
PASSWORDS = {
    "base.pdf": ["foo"],
    "rc4-40.pdf": ["foo"],
    "rc4-128.pdf": ["foo"],
    "aes-128.pdf": ["foo"],
    "aes-128-m.pdf": ["foo"],
    "aes-256.pdf": ["foo"],
    "aes-256-m.pdf": ["foo"],
    "aes-256-r6.pdf": ["usersecret", "ownersecret"],
}


@pytest.mark.parametrize("path", ALLPDFS, ids=str)
def test_open(path: Path):
    """Open all the documents"""
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        with playa.open(TESTDIR / path, password=password) as pdf:
            pass
        assert pdf._parser.fp.closed
