"""
Test PLAYA integration with various kinds of bears (polars, pandas).
"""

from pathlib import Path

try:
    import polars as pl
except ImportError:
    pl = None  # type: ignore

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore

import pytest
import playa

TESTDIR = Path(__file__).parent.parent / "samples"


@pytest.mark.skipif(pd is None, reason="Pandas is not installed")
def test_pandas_dataframe():
    """Load from PLAYA to Pandas"""
    with playa.open(TESTDIR / "pdf_structure.pdf") as pdf:
        df = pd.DataFrame(pdf.layout)
        assert len(df) == 1093


@pytest.mark.skipif(pl is None, reason="Polars is not instaled")
def test_polars_dataframe():
    """Load from PLAYA to Pandas"""
    with playa.open(TESTDIR / "pdf_structure.pdf") as pdf:
        df = pl.DataFrame(pdf.layout, schema=playa.schema)
        assert len(df) == 1093
