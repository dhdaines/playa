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
def test_open(path: Path) -> None:
    """Open all the documents"""
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        with playa.open(TESTDIR / path, password=password) as _pdf:
            pass


def test_analyze() -> None:
    """Test the layout analyzer (FIXME: PLAYA Ain't a Layout Analyzer)"""
    with playa.open(
        TESTDIR / "2023-04-06-ODJ et Résolutions-séance xtra 6 avril 2023.pdf"
    ) as pdf:
        for page in pdf.pages:
            page_objs = list(page.layout)
            print(len(page_objs))


def test_inline_data() -> None:
    # No, there's no easy way to unit test PDFContentParser directly.
    # The necessary mocking would be useless considering that I will
    # shortly demolish these redundant and confusing APIs.
    with playa.open(TESTDIR / "contrib" / "issue-1008-inline-ascii85.pdf") as doc:
        _ = doc.pages[0].layout


def test_multiple_contents() -> None:
    with playa.open(TESTDIR / "jo.pdf") as doc:
        page = doc.pages[0]
        assert len(page.contents) > 1
        _ = page.layout


def test_weakrefs() -> None:
    """Verify that PDFDocument really gets deleted even if we have
    PDFObjRefs hanging around."""
    with playa.open(TESTDIR / "simple5.pdf") as doc:
        ref = doc.catalog["Pages"]
    del doc
    with pytest.raises(RuntimeError):
        _ = ref.resolve()


if __name__ == "__main__":
    test_open(TESTDIR / "simple5.pdf")
