"""
Lists of data files and directories to be shared by various tests.
"""

from pathlib import Path
import json

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
    with open(PDFJS / "test_manifest.json") as infh:
        manifest = json.load(infh)
    for entry in manifest:
        path = PDFJS / entry["file"]
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
    "empty.pdf",
    # pdf.js accepts these... maybe some day we will but they are
    # really rather broken.
    "issue9418.pdf",
    "bug1250079.pdf",
    # FIXME: We "accept" these but the Unicode mappings are incorrect.
    # Need to see what pdf.js does for them - it seems falling back to
    # the string may work, but it might be ASCII, PDFDocEncoding,
    # UTF-16BE, or UTF-8 (each of these is different), so...
    "issue9915_reduced.pdf",
    "issue2931.pdf",
    "issue9534_reduced.pdf",
    "issue18117.pdf",
}
