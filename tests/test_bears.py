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


def test_polars_dataframe():
    """Load from PLAYA to Pandas"""
    with playa.open(TESTDIR / "pdf_structure.pdf") as pdf:
        df = pl.DataFrame(pdf.layout, schema=playa.schema, strict=False)
        assert len(df) == 1093
