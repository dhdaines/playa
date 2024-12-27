"""Demonstrate paralle extraction with pdfminer.six"""
import time
from pdfminer.high_level import extract_pages
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from pdfminer.pdfpage import PDFPage
from pdfminer.layout import LTImage
from pdfminer.pdftypes import PDFObjRef


def benchmark_single(path: Path):
    for page in extract_pages(path):
        pass


def remove_references(item):
    try:
        for child in item:
            remove_references(child)
    except TypeError:
        if isinstance(item, LTImage):
            for key, val in item.stream.attrs.items():
                if isinstance(val, PDFObjRef):
                    val.doc = None


def extract_batch(path, page_numbers):
    batch = list(extract_pages(path, page_numbers=page_numbers))
    remove_references(batch)
    return batch


def benchmark_multi(path: Path, ncpu: int):
    with open(path, "rb") as fp:
        npages = sum(1 for _ in PDFPage.get_pages(fp))
    pages = [None] * npages
    batches = []

    with ProcessPoolExecutor(max_workers=ncpu) as pool:
        step = max(1, round(npages / ncpu))
        for start in range(0, npages, step):
            end = min(npages, start + step)
            batch = list(range(start, end))
            print(f"Submitting pages {start} to {end - 1}")
            batches.append((batch,
                            pool.submit(extract_batch, path, batch)))
    for batch, future in batches:
        for idx, page in zip(batch, future.result()):
            pages[idx] = page


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--ncpu", type=int, default=4)
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()

    start = time.time()
    benchmark_multi(args.pdf, args.ncpu)
    multi_time = time.time() - start
    print("pdfminer.six (%d CPUs) took %.2fs" % (args.ncpu, multi_time,))

    start = time.time()
    benchmark_single(args.pdf)
    single_time = time.time() - start
    print("pdfminer.six (single) took %.2fs" % (single_time,))
