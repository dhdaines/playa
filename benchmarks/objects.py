"""
Benchmark the converter on all of the sample documents.
"""

import logging
import time
from pathlib import Path

import playa
from playa import ContentObject, Rect

LOG = logging.getLogger("benchmark-convert")
# Use a standard benchmark set to make version comparisons possible
CONTRIB = Path(__file__).parent.parent / "samples" / "contrib"
PDFS = [
    "PSC_Station.pdf",
    "Rgl-1314-2021-DM-Derogations-mineures.pdf",
]


def benchmark_one_lazy(path: Path):
    """Open one of the documents"""
    with playa.open(path) as pdf:
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
        for name in PDFS:
            path = CONTRIB / name
            start = time.time()
            benchmark_one_lazy(path)
            if iter != 0:
                lazy_time += time.time() - start
    print("Object types took %d ms / iter" % (lazy_time / niter * 1000,))
