"""
Attempt to scale.
"""

import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import List

import playa
from playa.page import Page


def process_page(page: Page) -> List:
    return [obj.bbox for obj in page]


def benchmark_single(path: Path):
    global pdf, pages
    with playa.open(path) as pdf:
        boxes = list(map(process_page, pdf.pages))


def open_doc_g(path: Path):
    global pdf, pages
    pdf = playa.open(path)
    pages = pdf.pages


def process_page_g(idx) -> List:
    global pages
    return [obj.bbox for obj in pages[idx]]


def benchmark_multi(path: Path, ncpu: int):
    with playa.open(path) as pdf:
        npages = len(pdf.pages)
    with ProcessPoolExecutor(
        max_workers=ncpu,
        initializer=open_doc_g,
        initargs=(path,),
    ) as pool:
        boxes = list(pool.map(process_page_g, range(npages)))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--ncpu", type=int, default=4)
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()

    start = time.time()
    benchmark_multi(args.pdf, args.ncpu)
    multi_time = time.time() - start
    print("PLAYA (%d CPUs) took %.2fs" % (args.ncpu, multi_time,))

    start = time.time()
    benchmark_single(args.pdf)
    single_time = time.time() - start
    print("PLAYA (single) took %.2fs" % (single_time,))
