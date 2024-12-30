"""
Attempt to scale.
"""

import time
from pathlib import Path

import playa
from playa.page import Page


def process_page(page: Page) -> str:
    return " ".join(x.chars for x in page.texts)


def benchmark_single(path: Path):
    with playa.open(path) as pdf:
        return list(pdf.pages.map(process_page))


def benchmark_multi(path: Path, ncpu: int):
    with playa.open(path, max_workers=ncpu) as pdf:
        return list(pdf.pages.map(process_page))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--ncpu", type=int, default=4)
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()

    start = time.time()
    benchmark_multi(args.pdf, args.ncpu)
    multi_time = time.time() - start
    print(
        "PLAYA (%d CPUs) took %.2fs"
        % (
            args.ncpu,
            multi_time,
        )
    )

    start = time.time()
    benchmark_single(args.pdf)
    single_time = time.time() - start
    print("PLAYA (single) took %.2fs" % (single_time,))
