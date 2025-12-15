"""
Test the CLI
"""

from contextlib import redirect_stdout
from pathlib import Path

import pytest
import tempfile

from playa import PDFPasswordIncorrect
from playa.cli import main
from playa.exceptions import PDFEncryptionError
from tests.data import ALLPDFS, PASSWORDS, XFAILS, TESTDIR


@pytest.mark.parametrize("path", ALLPDFS, ids=str)
def test_cli_metadata(path: Path):
    if path.name in XFAILS:
        pytest.xfail("Expected failure: %s" % path.name)
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        try:
            # FIXME: Verify that output is valid JSON
            main(["--password", password, "--non-interactive", str(path)])
        except PDFPasswordIncorrect:
            pass
        except PDFEncryptionError:
            pytest.skip("cryptography package not installed")


@pytest.mark.parametrize("path", ALLPDFS, ids=str)
def test_cli_catalog(path: Path):
    if path.name in XFAILS:
        pytest.xfail("Expected failure: %s" % path.name)
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        try:
            # FIXME: Verify that output is valid JSON
            main(["--password", password, "--catalog", "--non-interactive", str(path)])
        except PDFPasswordIncorrect:
            pass
        except PDFEncryptionError:
            pytest.skip("cryptography package not installed")


@pytest.mark.parametrize("path", ALLPDFS, ids=str)
def test_cli_outline(path: Path):
    if path.name in XFAILS:
        pytest.xfail("Expected failure: %s" % path.name)
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        try:
            # FIXME: Verify that output is valid JSON
            main(["--password", password, "--non-interactive", "--outline", str(path)])
        except PDFPasswordIncorrect:
            pass
        except PDFEncryptionError:
            pytest.skip("cryptography package not installed")


@pytest.mark.parametrize("path", ALLPDFS, ids=str)
def test_cli_structure(path: Path):
    if path.name in XFAILS:
        pytest.xfail("Expected failure: %s" % path.name)
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        try:
            # FIXME: Verify that output is valid JSON
            main(
                ["--password", password, "--non-interactive", "--structure", str(path)]
            )
        except PDFPasswordIncorrect:
            pass
        except PDFEncryptionError:
            pytest.skip("cryptography package not installed")


@pytest.mark.parametrize("path", ALLPDFS, ids=str)
def test_cli_text(path: Path):
    if path.name in XFAILS:
        pytest.xfail("Expected failure: %s" % path.name)
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        try:
            main(["--password", password, "--non-interactive", "--text", str(path)])
        except PDFPasswordIncorrect:
            pass
        except PDFEncryptionError:
            pytest.skip("cryptography package not installed")


@pytest.mark.parametrize("path", ALLPDFS, ids=str)
def test_cli_content_objects(path: Path):
    if path.name in XFAILS:
        pytest.xfail("Expected failure: %s" % path.name)
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        try:
            # Avoid OOM errors from capturing too much output
            with redirect_stdout(None):
                main(
                    [
                        "--password",
                        password,
                        "--non-interactive",
                        "--content-objects",
                        str(path),
                    ]
                )
        except PDFPasswordIncorrect:
            pass
        except PDFEncryptionError:
            pytest.skip("cryptography package not installed")


@pytest.mark.parametrize("path", ALLPDFS, ids=str)
def test_cli_images(path: Path):
    if path.name in XFAILS:
        pytest.xfail("Expected failure: %s" % path.name)
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        try:
            # FIXME: Verify that output is valid JSON
            with tempfile.TemporaryDirectory() as tempdir:
                main(
                    [
                        "--password",
                        password,
                        "--non-interactive",
                        "--images",
                        tempdir,
                        str(path),
                    ]
                )
        except PDFPasswordIncorrect:
            pass
        except PDFEncryptionError:
            pytest.skip("cryptography package not installed")


@pytest.mark.parametrize("path", ALLPDFS, ids=str)
def test_cli_fonts(path: Path):
    if path.name in XFAILS:
        pytest.xfail("Expected failure: %s" % path.name)
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        try:
            # FIXME: Verify that output is valid JSON
            with tempfile.TemporaryDirectory() as tempdir:
                main(
                    [
                        "--password",
                        password,
                        "--non-interactive",
                        "--fonts",
                        tempdir,
                        str(path),
                    ]
                )
        except PDFPasswordIncorrect:
            pass
        except PDFEncryptionError:
            pytest.skip("cryptography package not installed")


def test_extract_stream():
    """Verify that stream extractor works right."""
    main(["-t", "2", str(TESTDIR / "pdf_structure.pdf")])


def test_extract_catalog():
    """Verify that catalog extractor works right."""
    main(["--catalog", str(TESTDIR / "pdf_structure.pdf")])


def test_page_specs():
    """Verify page specifications."""
    testpdf = str(TESTDIR / "font-size-test.pdf")
    main(["--pages", "all", "--text", testpdf])
    main(["--pages", "all,1,3", "--text", testpdf])
    main(["--pages", "1-2", "--text", testpdf])
    main(["--pages", "1-2,4,5", "--text", testpdf])
    main(["--pages", "10-4", "--text", testpdf])
    main(["--pages", "666-668", "--text", testpdf])
    main(["--pages", "668-666", "--text", testpdf])


def test_no_args():
    with pytest.raises(SystemExit):
        main([])


def test_bad_page_spec():
    testpdf = str(TESTDIR / "font-size-test.pdf")
    assert main(["--pages", "10-4,goodbuddy", "--text", testpdf]) != 0


def test_text_objects():
    testpdf = str(TESTDIR / "font-size-test.pdf")
    main(["--pages", "1,3", "--text-objects", testpdf])


def test_content_objects():
    testpdf = str(TESTDIR / "font-size-test.pdf")
    main(["--pages", "1,3", "--content-objects", testpdf])
    main(["--pages", "1,3", "--content-objects", "--explode-text", testpdf])


def test_content_streams():
    testpdf = str(TESTDIR / "font-size-test.pdf")
    main(["--pages", "1", "--content-streams", testpdf])
