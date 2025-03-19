"""
Benchmark text extraction on the sample documents.
"""

import logging
import time
from pathlib import Path

from tests.data import BASEPDFS, PASSWORDS, PDFMINER_BUGS, XFAILS

LOG = logging.getLogger("benchmark-text")


def benchmark_chars(path: Path):
    """Extract just the Unicode characters (a poor substitute for actual
    text extraction)"""
    import playa

    if path.name in PDFMINER_BUGS or path.name in XFAILS:
        return
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        LOG.info("Reading %s", path)
        with playa.open(path, password=password) as pdf:
            for page in pdf.pages:
                for obj in page.texts:
                    _ = obj.chars


def benchmark_text(path: Path):
    """Extract text, sort of."""
    import playa

    if path.name in PDFMINER_BUGS or path.name in XFAILS:
        return
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        LOG.info("Reading %s", path)
        with playa.open(path, password=password) as pdf:
            for page in pdf.pages:
                page.extract_text()


if __name__ == "__main__":
    # Silence warnings about broken PDFs
    logging.basicConfig(level=logging.ERROR)
    niter = 5
    chars_time = text_time = 0.0
    for iter in range(niter + 1):
        for path in BASEPDFS:
            start = time.time()
            benchmark_chars(path)
            if iter != 0:
                chars_time += time.time() - start
            start = time.time()
            benchmark_text(path)
            if iter != 0:
                text_time += time.time() - start
    print("chars took %.2fs / iter" % (chars_time / niter,))
    print("extract_text took %.2fs / iter" % (text_time / niter,))
