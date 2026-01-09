"""
Test pdfminer.six replacement functionality.
"""

from playa.miner import (
    extract,
    LAParams,
    LTFigure,
    LTTextLine,
    LTComponent,
    make_path_segment,
)
from pdfminer.high_level import extract_pages as pdfminer_extract_pages
from tests.data import TESTDIR, CONTRIB, XFAILS, PDFMINER_BUGS
from pathlib import Path
import pytest
import re
from typing import Any


# For the moment test a restricted set of PDFs as we are not totally
# bug-compatible with pdfminer.six
TESTPDFS = [
    (TESTDIR / name)
    for name in [
        "core_font_encodings.pdf",
        "font-size-test.pdf",
        "hello_structure.pdf",
        "simple1.pdf",
        "simple2.pdf",
        #    "vertical_writing.pdf",
        "zen_of_python_corrupted.pdf",
    ]
]


def compare(playa_item: Any, pdfminer_item: Any) -> None:
    """Compare PLAYA and pdfminer.six accounting for some differences."""
    pvstr = str(playa_item)
    pmstr = str(pdfminer_item)
    # Remove (cid:N) as PLAYA does not do that
    pmstr = re.sub(r"\(cid:\d+\)", "", pmstr)
    assert pvstr == pmstr


@pytest.mark.parametrize("path", TESTPDFS, ids=str)
def test_extract(path: Path):
    if path.name in XFAILS:
        pytest.xfail("Expected failure: %s" % path.name)
    if path.name in PDFMINER_BUGS:
        pytest.xfail("Skipping pdfminer.six failure: %s" % path.name)
    for idx, (playa_ltpage, pdfminer_ltpage) in enumerate(
        zip(extract(path, LAParams()), pdfminer_extract_pages(path))
    ):
        # Otherwise pdfminer.six is just too darn slow
        if idx == 20:
            break
        for playa_item, pdfminer_item in zip(playa_ltpage, pdfminer_ltpage):
            compare(playa_item, pdfminer_item)


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_serialization():
    """Ensure stuff is reserialized properly"""
    path = CONTRIB / "PSC_Station.pdf"
    pages = extract(path, LAParams())
    first = next(pages)
    for item in first:
        if isinstance(item, LTFigure):
            img = next(iter(item))
            # We have a image stream
            assert len(img.stream.buffer) == 52692
            assert img.colorspace.name == "ICCBased"
            # It has a colorspace, which has a stream as an indirect
            # object reference, which we can resolve
            icc = img.colorspace.spec[1].resolve()
            assert len(icc.buffer) == 3144
        # Probably we could test some other things too?


def test_make_path_segment() -> None:
    """Verify make_path_segment works"""
    assert make_path_segment("h", []) == ("h",)
    # NOTE: This is the bogus output type for bug compatibility with pdfminer.six
    assert make_path_segment("m", [(1, 2)]) == ("m", (1, 2))
    assert make_path_segment("l", [(3, 4)]) == ("l", (3, 4))
    assert make_path_segment("v", [(3, 4), (5, 6)]) == ("v", (3, 4), (5, 6))
    assert make_path_segment("y", [(3, 4), (5, 6)]) == ("y", (3, 4), (5, 6))
    assert make_path_segment("c", [(1, 2), (3, 4), (5, 6)]) == (
        "c",
        (1, 2),
        (3, 4),
        (5, 6),
    )
    with pytest.raises(ValueError):
        make_path_segment("h", [(1, 2)])
        make_path_segment("m", [(1, 2), (3, 4)])
        make_path_segment("l", [(1, 2), (3, 4)])
        make_path_segment("v", [(1, 2)])
        make_path_segment("y", [(1, 2)])
        make_path_segment("c", [(1, 2)])


def test_items_are_hashable_and_serializable() -> None:
    """Verify that we can hash and serialize LTThingies"""
    import pickle

    assert hash(LTTextLine(0.3))
    assert hash(LTComponent((1, 2, 3, 4), ()))
    data = pickle.dumps(LTComponent((1, 2, 3, 4), ()))
    assert hash(pickle.loads(data))


if __name__ == "__main__":
    test_extract()
