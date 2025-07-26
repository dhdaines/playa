"""
Benchmark type3 charprocs.
"""

import logging
import time
from pathlib import Path

import playa

CONTRIB = Path(__file__).parent.parent / "samples" / "contrib"

LOG = logging.getLogger("benchmark-text")
PDFS = ["scp05.pdf"]


def benchmark_type3_charprocs(path: Path):
    with playa.open(path) as pdf:
        for page in pdf.pages:
            for glyph in page.glyphs:
                for obj in glyph:
                    _ = obj


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    niter = 1
    t = 0.0
    for iter in range(niter + 1):
        for name in PDFS:
            path = CONTRIB / name
            start = time.time()
            benchmark_type3_charprocs(path)
            if iter != 0:
                t += time.time() - start
    print("charprocs took %d ms / iter" % (t / niter * 1000,))
