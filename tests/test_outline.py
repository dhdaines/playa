"""
Test document outline.
"""

from typing import List

import playa
from playa.outline import Outline

from .data import TESTDIR


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


if __name__ == '__main__':
    test_outline()
