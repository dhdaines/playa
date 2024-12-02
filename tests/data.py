"""
Lists of data files and directories to be shared by various tests.
"""

from pathlib import Path
import json

TESTDIR = Path(__file__).parent.parent / "samples"
SUBDIRS = ["acroform", "encryption", "scancode"]
ALLPDFS = list(TESTDIR.glob("*.pdf"))
for name in SUBDIRS:
    ALLPDFS.extend((TESTDIR / name).glob("*.pdf"))
CONTRIB = TESTDIR / "contrib"
if CONTRIB.exists():
    ALLPDFS.extend(CONTRIB.glob("*.pdf"))
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
    "bogus-stream-length.pdf",
    "empty.pdf",
}