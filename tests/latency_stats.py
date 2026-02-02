"""
Get statistics on latency for all the PDFs
"""

import logging
import sys
import time
from pathlib import Path

import playa
from .data import ALLPDFS, XFAILS, PASSWORDS

HERE = Path.cwd()


def main() -> None:
    open_time = []
    cat_time = []
    page_time = []
    logging.basicConfig(level=logging.ERROR)
    print("recalculating", end="", file=sys.stderr, flush=True)
    for path in ALLPDFS:
        p = Path(str(path.values[0]))
        if p.name in XFAILS:
            continue
        passwords = PASSWORDS.get(p.name, [""])
        for password in passwords:
            try:
                start = time.time()
                pdf = playa.open(p, password=password)
                open_time.append((time.time() - start, p.relative_to(HERE)))
                _ = pdf.catalog
                cat_time.append((time.time() - start, p.relative_to(HERE)))
                try:
                    _ = next(iter(pdf.pages))
                    page_time.append((time.time() - start, p.relative_to(HERE)))
                except StopIteration:
                    pass
                print(".", end="", file=sys.stderr, flush=True)
            except playa.PDFEncryptionError:
                pass
    print(file=sys.stderr)
    report("open", open_time)
    print()
    report("catalog", cat_time)
    print()
    report("page 1", page_time)


def report(name: str, stats: list[tuple[float, Path]]) -> None:
    stats.sort(reverse=True)
    print(f"{name}:")
    med_time, med_path = stats[len(stats) // 2]
    print("    median: %.2fms %s" % (med_time * 1000, med_path))
    print("  sorted:")
    for t, p in stats:
        print("    %.2fms %s" % (t * 1000, p))


if __name__ == "__main__":
    main()
