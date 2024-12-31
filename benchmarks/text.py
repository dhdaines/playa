"""
Benchmark text extraction on the sample documents.
"""

import logging
import time
from pathlib import Path
from tests.data import BASEPDFS, PASSWORDS, XFAILS
from tests.test_open import PDFMINER_BUGS

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


if __name__ == "__main__":
    # Silence warnings about broken PDFs
    logging.basicConfig(level=logging.ERROR)
    niter = 5
    miner_time = beach_time = lazy_time = 0.0
    for iter in range(niter + 1):
        for path in BASEPDFS:
            start = time.time()
            benchmark_chars(path)
            if iter != 0:
                lazy_time += time.time() - start
    print("chars took %.2fs / iter" % (lazy_time / niter,))
