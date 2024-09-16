# PLAYA is a LAYout Analyzer 🏖️

## About

This is not an experimental fork of
[pdfminer.six](https://github.com/pdfminer/pdfminer.six).  Well, it's
kind of an experimental fork of pdfminer.six.  The idea is to extract
just the part of pdfminer.six that gets used these days, namely the
layout analysis and low-level PDF access, see if it can be
reimplemented using other libraries such as pypdf or pikepdf, and make
its API more fun to use.

There are already too many PDF libraries, unfortunately none of which
does everything that everybody wants it to do, and we probably don't
need another one. It is not recommended that you use this library for
anything at all, but if you were going to use it for something, it
would be specifically one of these things and nothing else:

1. Accessing the document catalog, page tree, structure tree, content
   streams, cross-reference table, XObjects, and other low-level PDF
   metadata.
2. Obtaining the absolute position and attributes of every character,
   line, path, and image in every page of a PDF document.

Since most people *do not want to do these things*, ideally, this will
get merged into some other library, perhaps
[pypdf](https://github.com/py-pdf/pypdf).  Did I mention this is
experimental?

## Acknowledgement

This repository obviously includes code from `pdfminer.six`.  Original
license text is included in [LICENSE](/LICENSE.pdfminer).  The license
itself has not changed!
