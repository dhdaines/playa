"""
Test rudimentary text extraction functionality.
"""

import playa

from .data import TESTDIR


def test_spaces_between_objects() -> None:
    """Make sure we can insert spaces between TextObjects on the same "line"."""
    with playa.open(TESTDIR / "graphics_state_in_text_object.pdf") as pdf:
        text = pdf.pages[0].extract_text()
        assert text == "foo  A B CDBAR\nFOOHello World"
