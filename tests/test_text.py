"""
Test rudimentary text extraction functionality.
"""

import pytest

import playa

from .data import TESTDIR, CONTRIB


def test_exotic_ctm() -> None:
    """Make sure text extraction works even when the CTM is weird."""
    with playa.open(TESTDIR / "zen_of_python_corrupted.pdf") as pdf:
        text = pdf.pages[0].extract_text()
        assert text.startswith("""\
Beautiful is better than ugly.
Explicit is better than implicit.
Simple is better than complex.""")


def test_spaces_between_objects() -> None:
    """Make sure we can insert spaces between TextObjects on the same "line"."""
    with playa.open(TESTDIR / "graphics_state_in_text_object.pdf") as pdf:
        text = pdf.pages[0].extract_text()
        assert text == "foo A B CDBAR\nFOOHello World"


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_tagged_line_breaks() -> None:
    """Make sure we only insert line breaks between marked content
    where there are actually line breaks."""
    with playa.open(CONTRIB / "2023-06-20-PV.pdf") as pdf:
        text = pdf.pages[0].extract_text()
        assert "4. Demande" in text
