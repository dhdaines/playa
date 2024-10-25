"""
Perhaps excessively hierarchical exception hierarchy.
"""


class PSException(Exception):
    pass


class PSEOF(PSException):
    pass


class PSSyntaxError(PSException):
    pass


class PSTypeError(PSException):
    pass


class PSValueError(PSException):
    pass


class PDFException(PSException):
    pass


class PDFSyntaxError(PDFException):
    pass


class PDFTypeError(PDFException, TypeError):
    pass


class PDFValueError(PDFException, ValueError):
    pass


class PDFNotImplementedError(PDFException, NotImplementedError):
    pass


class PDFKeyError(PDFException, KeyError):
    pass


class PDFEOFError(PDFException, EOFError):
    pass


class PDFIOError(PDFException, IOError):
    pass


class PDFInterpreterError(PDFException):
    pass


class PDFNoValidXRef(PDFSyntaxError):
    pass


class PDFNoOutlines(PDFException):
    pass


class PDFNoPageLabels(PDFException):
    pass


class PDFNoPageTree(PDFException):
    pass


class PDFNoStructTree(PDFException):
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
