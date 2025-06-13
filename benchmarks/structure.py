"""
Benchmark logical structure tree parsing on some sample documents.
"""

import logging
import time
from pathlib import Path

import playa
from playa.cli import extract_structure

SAMPLES = Path(__file__).parent.parent / "samples"
CONTRIB = Path(__file__).parent.parent / "samples" / "contrib"

LOG = logging.getLogger("benchmark-text")
# Use a standard benchmark set to make version comparisons possible
PDFS = [
    "2023-04-06-ODJ et Résolutions-séance xtra 6 avril 2023.pdf",
    "2023-06-20-PV.pdf",
    "PSC_Station.pdf",
    "Rgl-1314-2021-DM-Derogations-mineures.pdf",
]


def benchmark_cli(path: Path) -> None:
    from argparse import Namespace

    with open("/dev/null", "w") as out:
        args = Namespace(outfile=out)
        with playa.open(path) as doc:
            extract_structure(doc, args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    niter = 5
    cli_time = 0.0
    for iter in range(niter + 1):
        for name in PDFS:
            path = SAMPLES / name
            if not path.exists():
                path = CONTRIB / name
            start = time.time()
            benchmark_cli(path)
            if iter != 0:
                cli_time += time.time() - start
    print("CLI took %d ms / iter" % (cli_time / niter * 1000,))
