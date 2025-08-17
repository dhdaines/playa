"""
Lists of data files and directories to be shared by various tests.
"""

import json
from pathlib import Path

import pytest

TESTDIR = Path(__file__).parent.parent / "samples"
SUBDIRS = ["acroform", "encryption", "scancode"]
BASEPDFS = list(TESTDIR.glob("*.pdf"))
ALLPDFS = [pytest.param(path) for path in BASEPDFS]
for name in SUBDIRS:
    ALLPDFS.extend(pytest.param(path) for path in (TESTDIR / name).glob("*.pdf"))
CONTRIB = TESTDIR / "contrib"
if CONTRIB.exists():
    ALLPDFS.extend(
        pytest.param(path, marks=pytest.mark.contrib) for path in CONTRIB.glob("*.pdf")
    )

PLUMBERS = TESTDIR / "3rdparty" / "pdfplumber" / "tests" / "pdfs"
if PLUMBERS.exists():
    ALLPDFS.extend(
        pytest.param(path, marks=pytest.mark.thirdparty)
        for path in PLUMBERS.glob("*.pdf")
    )
PDFJS = TESTDIR / "3rdparty" / "pdf.js" / "test"
try:
    with open(PDFJS / "test_manifest.json", encoding="utf-8") as infh:
        manifest = json.load(infh)
    seen = set()
    for entry in manifest:
        path = PDFJS / entry["file"]
        if entry["file"] in seen:
            continue
        seen.add(entry["file"])
        if path.exists():
            ALLPDFS.append(pytest.param(path, marks=pytest.mark.thirdparty))
except FileNotFoundError:
    pass

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
XFAILS = {
    # can't mmap an empty file... don't even try!
    "empty.pdf",
    # pdf.js accepts these... maybe some day we will but they are
    # really rather broken.
    "issue9418.pdf",
    "bug1250079.pdf",
    "issue13147.pdf",
    # FIXME: These seem to be due to problems in the Unicode mappings
    # we inherited from pdfminer.six
    "JST2007-5.pdf",
    "P020121130574743273239.pdf",
    "SFAA_Japanese.pdf",
    "issue2829.pdf",
    "issue11526.pdf",
    # Excessively huge indexed image takes forever
    "issue17190_1.pdf",
    # Totally broken pdf, no catalog to be found
    "issue-154.pdf",
}
# We know pdfminer.six gives different output for these and we don't
# care (generally because of PLAYA's better rectangle detection and
# correct bboxes for rotated glyphs)
PDFMINER_BUGS = {
    "issue-449-vertical.pdf",
    "issue_495_pdfobjref.pdf",
    "issue-886-xref-stream-widths.pdf",
    "issue-1004-indirect-mediabox.pdf",
    "issue-1008-inline-ascii85.pdf",
    "issue-1059-cmap-decode.pdf",
    "issue-1062-filters.pdf",
    "rotated.pdf",
    "issue-1114-dedupe-chars.pdf",
    "malformed-from-issue-932.pdf",
    "mcid_example.pdf",
    "utf8_tounicode.pdf",
    "utf16_tounicode.pdf",
    "ascii_tounicode.pdf",
    "duplicate_encoding_tounicode.pdf",
    # Except this one here where pdfminer.six will just crash
    "evil_xobjects.pdf",
}
# Broken XRef tables (bogus linearization, concatenation, etc)
FALLBACKS = {
    "samples/3rdparty/pdf.js/test/pdfs/issue11230.pdf",
    "samples/3rdparty/pdf.js/test/pdfs/issue12402.pdf",
    "samples/3rdparty/pdf.js/test/pdfs/issue13783.pdf",
    "samples/3rdparty/pdf.js/test/pdfs/issue14269.pdf",
    "samples/3rdparty/pdf.js/test/pdfs/issue1536.pdf",
    "samples/3rdparty/pdf.js/test/pdfs/issue7303.pdf",
    "samples/3rdparty/pdf.js/test/pdfs/issue9129.pdf",
    "samples/3rdparty/pdf.js/test/pdfs/issue9552.pdf",
}
