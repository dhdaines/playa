"""
Test PLAYA integration with various kinds of bears (polars, pandas).
"""

from pathlib import Path

import polars as pl
import pandas as pd

import playa

TESTDIR = Path(__file__).parent.parent / "samples"


def test_pandas_dataframe():
    """Load from PLAYA to Pandas"""
    with playa.open(TESTDIR / "pdf_structure.pdf") as pdf:
        df = pd.DataFrame(pdf.layout)
        assert len(df) == 1093


SCHEMA = {
    "object_type": str,
    "mcid": int,
    "tag": str,
    "xobjid": str,
    "text": str,
    "fontname": str,
    "size": float,
    "adv": float,
    "matrix": pl.Array(float, 6),
    "upright": bool,
    "x0": float,
    "x1": float,
    "y0": float,
    "y1": float,
    "scs": pl.Object,
    "ncs": pl.Object,
    "stroking_color": pl.Object,
    "non_stroking_color": pl.Object,
    "path": pl.Object,
    # "dash": pl.Object,  # WTF
    "evenodd": bool,
    "stroke": bool,
    "fill": bool,
    "linewidth": float,
    "pts": pl.Object,
    "stream": pl.Object,
    "imagemask": bool,
    "colorspace": pl.Object,
    "srcsize": pl.Array(int, 2),
    "bits": int,
    "page_index": int,
    "page_label": str,
}


def test_polars_dataframe():
    """Load from PLAYA to Pandas"""
    with playa.open(TESTDIR / "pdf_structure.pdf") as pdf:
        df = pl.DataFrame(pdf.layout, schema=SCHEMA, strict=False)
        print(df)
