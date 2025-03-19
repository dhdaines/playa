"""
Test document outline.
"""

from typing import List

import pytest

import playa
from playa.exceptions import PDFEncryptionError
from playa.outline import Outline

from .data import ALLPDFS, PASSWORDS, TESTDIR, XFAILS


def expand_titles(outline: Outline) -> List:
    def expand_one(child):
        out = [child.title]
        for c in child:
            out.append(expand_one(c))
        return out

    out = []
    for child in outline:
        out.extend(expand_one(child))
    return out


def test_outline():
    """Test basic outline functionality."""
    with playa.open(TESTDIR / "pdf_structure.pdf") as pdf:
        titles = expand_titles(pdf.outline)
        assert titles == ["Titre 1", ["Titre 2", ["Tableau"]]]


def expand(outline: Outline) -> List:
    def expand_one(child, level=1):
        out = [child.title, child.destination, child.element]
        # Limit depth to avoid taking all memory
        if level == 3:
            return out
        for c in child:
            out.append(expand_one(c, level + 1))
        return out

    out = []
    for idx, child in enumerate(outline):
        # Limit number to avoid taking all memory
        if idx == 10:
            break
        out.extend(expand_one(child))
    return out


@pytest.mark.parametrize("path", ALLPDFS, ids=str)
def test_outlines(path) -> None:
    """Verify that we can read outlines when they exist."""
    if path.name in XFAILS:
        pytest.xfail("Intentionally corrupt file: %s" % path.name)
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        try:
            with playa.open(path, password=password) as pdf:
                outline = pdf.outline
                if outline is not None:
                    print(expand(outline))
        except PDFEncryptionError:
            pytest.skip("password incorrect or cryptography package not installed")


@pytest.mark.parametrize("path", ALLPDFS, ids=str)
def test_destinations(path) -> None:
    """Verify that we can read destinations when they exist."""
    if path.name in XFAILS:
        pytest.xfail("Intentionally corrupt file: %s" % path.name)
    if path.name == "issue2098.pdf":
        pytest.skip("Skipping excessively borken PDF with bad destinations")
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        try:
            with playa.open(path, password=password) as pdf:
                for idx, k in enumerate(pdf.destinations):
                    _ = pdf.destinations[k]
                    # FIXME: Currently getting destinations is quite
                    # slow, so only do a few of them.
                    if idx == 300:
                        break
        except PDFEncryptionError:
            pytest.skip("password incorrect or cryptography package not installed")
