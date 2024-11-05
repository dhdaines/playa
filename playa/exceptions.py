"""
Some PLAYA-specific exceptions to cover PDF-specific problems
"""


class PDFException(Exception):
    pass


class PDFSyntaxError(PDFException):
    pass


class PDFInterpreterError(PDFException):
    pass


class PDFEncryptionError(PDFException):
    pass


class PDFPasswordIncorrect(PDFEncryptionError):
    pass


class PDFTextExtractionNotAllowed(PDFEncryptionError):
    pass


class PDFFontError(PDFException):
    pass


class PDFUnicodeNotDefined(PDFFontError):
    pass
