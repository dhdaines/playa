"""Benchmark pdfminer.six against PLAYA"""

import time
from typing import Union
from pdfminer.high_level import extract_pages
from playa.miner import extract, LAParams
from pathlib import Path
import logging

SAMPLES = Path(__file__).parent.parent / "samples"
CONTRIB = Path(__file__).parent.parent / "samples" / "contrib"

LOG = logging.getLogger("benchmark-miner")
# Use a standard benchmark set to make version comparisons possible
PDFS = [
    "2023-04-06-ODJ et Résolutions-séance xtra 6 avril 2023.pdf",
    "2023-06-20-PV.pdf",
    "PSC_Station.pdf",
    "Rgl-1314-2021-DM-Derogations-mineures.pdf",
]


def benchmark_single(path: Path):
    for page in extract_pages(path):
        pass


def benchmark_multi(path: Path, ncpu: Union[int, None]):
    for page in extract(path, laparams=LAParams(), max_workers=ncpu):
        pass


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--ncpu", type=int, default=1)
    parser.add_argument("--no-miner", action="store_true")
    parser.add_argument("--no-paves", action="store_true")
    parser.add_argument("pdf", type=Path, nargs="*", default=PDFS)
    args = parser.parse_args()

    if not args.no_paves:
        start = time.time()
        for name in args.pdf:
            benchmark_multi(CONTRIB / name, args.ncpu)
        multi_time = time.time() - start
        print(
            "PLAYA (%r CPUs) took %.2fs"
            % (
                args.ncpu,
                multi_time,
            )
        )

    if not args.no_miner:
        start = time.time()
        for name in args.pdf:
            benchmark_single(CONTRIB / name)
        single_time = time.time() - start
        print("pdfminer.six (single) took %.2fs" % (single_time,))
