"""
Attempt to scale.
"""

import time
from pathlib import Path

import playa
from playa.page import Page

CONTRIB = Path(__file__).parent.parent / "samples" / "contrib"


def process_page(page: Page) -> None:
    for obj in page:
        _ = obj.bbox


def benchmark_single(path: Path):
    with playa.open(path) as pdf:
        list(pdf.pages.map(process_page))


def benchmark_multi(path: Path, ncpu: int):
    with playa.open(path, max_workers=ncpu) as pdf:
        list(pdf.pages.map(process_page))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--ncpu", type=int, default=2)
    parser.add_argument("-i", "--niter", type=int, default=5)
    parser.add_argument(
        "--pdf",
        type=Path,
        default=CONTRIB / "Rgl-1314-2021-DM-Derogations-mineures.pdf",
    )
    args = parser.parse_args()

    multi_time = single_time = 0.0
    for iter in range(args.niter + 1):
        start = time.time()
        benchmark_multi(args.pdf, args.ncpu)
        if iter != 0:
            multi_time += time.time() - start
    print(
        "PLAYA (%d CPUs) took %d ms / iter"
        % (
            args.ncpu,
            multi_time / args.niter * 1000,
        )
    )

    for iter in range(args.niter + 1):
        start = time.time()
        benchmark_single(args.pdf)
        if iter != 0:
            single_time += time.time() - start
    print("PLAYA (single) took %d ms / iter" % (single_time / args.niter * 1000,))
