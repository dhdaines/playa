"""
Benchmark CCITT decoding.
"""

import logging
import time
from pathlib import Path

import playa

CONTRIB = Path(__file__).parent.parent / "samples" / "contrib"

LOG = logging.getLogger(Path(__file__).stem)
PDFS = ["ccitt-default-k.pdf", "ccitt_EndOfBlock_false.pdf"]


def benchmark_images(path: Path):
    with playa.open(path) as pdf:
        for page in pdf.pages:
            for image in page.images:
                _ = image.buffer


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    niter = 1
    t = 0.0
    for iter in range(niter + 1):
        for name in PDFS:
            path = CONTRIB / name
            start = time.time()
            benchmark_images(path)
            if iter != 0:
                t += time.time() - start
    print("ccitt took %d ms / iter" % (t / niter * 1000,))
