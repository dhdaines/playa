# PLAYA Ain't a LAYout Analyzer 🏖️

## About

This is not an experimental fork of
[pdfminer.six](https://github.com/pdfminer/pdfminer.six).  Well, it's
kind of an experimental fork of pdfminer.six.  The idea is to extract
just the part of pdfminer.six that gets used by
[pdfplumber](https://github.com/jsvine/pdfplumber), namely the
low-level PDF access, optimize it for speed, see if it can be
reimplemented using other libraries such as pypdf or pikepdf,
benchmark it against those libraries, and improve its API.

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
   
Notably this does *not* include the largely undocumented heuristic
"layout analysis" done by pdfminer.six, because it is quite difficult
to understand due to a Java-damaged API based on deeply nested class
hierarchies, and because layout analysis is best done
probabilistically/visually.  Also, pdfplumber does its own, much
nicer, layout analysis.

## Acknowledgement

This repository obviously includes code from `pdfminer.six`.  Original
license text is included in [LICENSE](/LICENSE.pdfminer).  The license
itself has not changed!
