"""
Test document outline.
"""

from typing import List

import playa
import pytest
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
        assert titles == ['Titre 1', ['Titre 2', ['Tableau']]]


def expand(outline: Outline) -> List:
    def expand_one(child):
        out = [child.title, child.destination, child.action, child.element]
        for c in child:
            out.append(expand_one(c))
        return out
    out = []
    for child in outline:
        out.extend(expand_one(child))
    return out


@pytest.mark.parametrize("path", ALLPDFS, ids=str)
def test_outlines(path) -> None:
    """Verify that we can read outlines and destinations when they exist."""
    if path.name in XFAILS:
        pytest.xfail("Intentionally corrupt file: %s" % path.name)
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        try:
            with playa.open(path, password=password) as pdf:
                outline = pdf.outline
                if outline is not None:
                    expand(outline)
        except PDFEncryptionError:
            pytest.skip("password incorrect or cryptography package not installed")


if __name__ == '__main__':
    test_outline()
