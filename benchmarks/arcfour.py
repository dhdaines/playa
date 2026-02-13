"""
Benchmark ArcFour "encryption"
"""

import logging
import time
from pathlib import Path

import playa

TESTDIR = Path(__file__).parent.parent / "samples" / "encryption"

LOG = logging.getLogger(Path(__file__).stem)
PDFS = ["rc4-128.pdf", "rc4-40.pdf"]


def benchmark(path: Path):
    with playa.open(path, password="foo") as pdf:
        for page in pdf.pages:
            for stream in page.streams:
                stream.decode()


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    niter = 10
    t = 0.0
    for iter in range(niter + 1):
        for name in PDFS:
            path = TESTDIR / name
            start = time.time()
            benchmark(path)
            if iter != 0:
                t += time.time() - start
    print("arcfour took %.2f ms / iter" % (t / niter * 1000,))
