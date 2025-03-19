"""
Test the CLI
"""

from pathlib import Path

import pytest

from playa import PDFPasswordIncorrect
from playa.cli import main
from playa.exceptions import PDFEncryptionError
from tests.data import ALLPDFS, PASSWORDS, XFAILS


@pytest.mark.parametrize("path", ALLPDFS, ids=str)
def test_cli_metadata(path: Path):
    if path.name in XFAILS:
        pytest.xfail("Intentionally corrupt file: %s" % path.name)
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        try:
            main(["--password", password, "--non-interactive", str(path)])
        except PDFPasswordIncorrect:
            pass
        except PDFEncryptionError:
            pytest.skip("cryptography package not installed")
