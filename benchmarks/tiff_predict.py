"""
Benchmark TIFF predictor
"""

import logging
import time
from pathlib import Path

import playa

CONTRIB = Path(__file__).parent.parent / "samples"

LOG = logging.getLogger(Path(__file__).stem)
PDFS = [
    "test_pdf_with_tiff_predictor.pdf",
]


def benchmark_images(path: Path):
    with playa.open(path) as pdf:
        for page in pdf.pages:
            for image in page.images:
                _ = image.buffer


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    niter = 100
    t = 0.0
    for iter in range(niter + 1):
        for name in PDFS:
            path = CONTRIB / name
            start = time.time()
            benchmark_images(path)
            if iter != 0:
                t += time.time() - start
    print("predictors took %.2f ms / iter" % (t / niter * 1000,))
