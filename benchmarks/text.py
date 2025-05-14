"""
Benchmark text extraction on some sample documents.
"""

import logging
import time
from pathlib import Path

import playa

SAMPLES = Path(__file__).parent.parent / "samples"
CONTRIB = Path(__file__).parent.parent / "samples" / "contrib"

LOG = logging.getLogger("benchmark-text")
# Use a standard benchmark set to make version comparisons possible
PDFS = [
    "jo.pdf",
    "zen_of_python_corrupted.pdf",
    "2023-04-06-ODJ et Résolutions-séance xtra 6 avril 2023.pdf",
    "2023-06-20-PV.pdf",
    "PSC_Station.pdf",
    "Rgl-1314-2021-DM-Derogations-mineures.pdf",
]


def benchmark_chars(path: Path):
    """Extract just the Unicode characters (a poor substitute for actual
    text extraction)"""

    with playa.open(path) as pdf:
        for page in pdf.pages:
            for obj in page.texts:
                _ = obj.chars


def benchmark_text(path: Path):
    """Extract text, sort of."""
    with playa.open(path) as pdf:
        for page in pdf.pages:
            page.extract_text()


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    niter = 5
    chars_time = text_time = 0.0
    for iter in range(niter + 1):
        for name in PDFS:
            path = SAMPLES / name
            if not path.exists():
                path = CONTRIB / name
            start = time.time()
            benchmark_chars(path)
            if iter != 0:
                chars_time += time.time() - start
            start = time.time()
            benchmark_text(path)
            if iter != 0:
                text_time += time.time() - start
    print("chars took %d ms / iter" % (chars_time / niter * 1000,))
    print("extract_text took %d ms / iter" % (text_time / niter * 1000,))
