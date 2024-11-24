"""
Basic CLI for Playa's "eager" API.  Writes CSV to standard output.
"""

import argparse
import csv
from pathlib import Path

import playa


def make_argparse() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdfs", nargs="+", type=Path)
    parser.add_argument(
        "-o",
        "--outfile",
        help="File to write output CSV (or - for standard output)",
        type=argparse.FileType("wt"),
        default="-",
    )
    parser.add_argument(
        "-s",
        "--space",
        help="Coordinate space for output objects",
        choices=["screen", "page", "user"],
        default="screen",
    )
    return parser


def main() -> None:
    parser = make_argparse()
    args = parser.parse_args()
    writer = csv.DictWriter(args.outfile, fieldnames=playa.fieldnames)
    writer.writeheader()
    for path in args.pdfs:
        with playa.open(path, space=args.space) as doc:
            for dic in doc.layout:
                writer.writerow(dic)


if __name__ == "__main__":
    main()
