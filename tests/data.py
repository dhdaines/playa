"""
Lists of data files and directories to be shared by various tests.
"""

import json
from pathlib import Path

TESTDIR = Path(__file__).parent.parent / "samples"
SUBDIRS = ["acroform", "encryption", "scancode"]
BASEPDFS = list(TESTDIR.glob("*.pdf"))
for name in SUBDIRS:
    BASEPDFS.extend((TESTDIR / name).glob("*.pdf"))
CONTRIB = TESTDIR / "contrib"
if CONTRIB.exists():
    BASEPDFS.extend(CONTRIB.glob("*.pdf"))

ALLPDFS = list(BASEPDFS)
PLUMBERS = TESTDIR / "3rdparty" / "pdfplumber" / "tests" / "pdfs"
if PLUMBERS.exists():
    ALLPDFS.extend(PLUMBERS.glob("*.pdf"))
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
            ALLPDFS.append(path)
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
    # FIXME: These seem to be due to problems in the Unicode mappings
    # we inherited from pdfminer.six
    "JST2007-5.pdf",
    "P020121130574743273239.pdf",
    "SFAA_Japanese.pdf",
    "issue2829.pdf",
    "issue11526.pdf",
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
}
