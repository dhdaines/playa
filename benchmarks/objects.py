"""
Benchmark the converter on all of the sample documents.
"""

import logging
import time
from pathlib import Path

from playa import ContentObject, Rect
from tests.data import BASEPDFS, PASSWORDS, PDFMINER_BUGS, XFAILS

LOG = logging.getLogger("benchmark-convert")


def benchmark_one_lazy(path: Path):
    """Open one of the documents"""
    import playa

    if path.name in PDFMINER_BUGS or path.name in XFAILS:
        return
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        LOG.info("Reading %s", path)
        with playa.open(path, password=password) as pdf:
            for page in pdf.pages:
                obj: ContentObject
                _: Rect
                for obj in page.texts:
                    _ = obj.bbox
                for obj in page.paths:
                    _ = obj.bbox
                for obj in page.images:
                    _ = obj.bbox
                for obj in page.xobjects:
                    _ = obj.bbox


if __name__ == "__main__":
    # Silence warnings about broken PDFs
    logging.basicConfig(level=logging.ERROR)
    niter = 5
    lazy_time = 0.0
    for iter in range(niter + 1):
        for path in BASEPDFS:
            start = time.time()
            benchmark_one_lazy(path)
            if iter != 0:
                lazy_time += time.time() - start
    print("Object types took %.2fs / iter" % (lazy_time / niter,))
