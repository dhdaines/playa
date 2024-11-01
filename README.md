# **P**LAYA ain't a **LAY**out **A**nalyzer 🏖️

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
nicer, layout analysis.  Also, if you just want to extract text from a
PDF, there are a lot of better and faster tools and libraries out
there, see [benchmarks]() for a summary (TL;DR pypdfium2 is probably
what you want, but pdfplumber does a nice job of converting PDF to
ASCII art).

## Usage

Do you want to get stuff out of a PDF?  You have come to the right
place!  Let's open up a PDF and see what's in it:

```python
pdf = playa.open("my_awesome_document.pdf")
raw_byte_stream = pdf.buffer
a_bunch_of_tokens = list(pdf.tokens)
a_bunch_of_objects = list(pdf)
a_particular_indirect_object = pdf[42]
```

The raw PDF tokens and objects are probably not terribly useful to
you, but you might find them interesting.

It probably has some pages.  How many?  What are their numbers/labels?
(they could be things like "xviii", 'a", or "42", for instance)

```python
npages = len(pdf.pages)
page_numbers = [page.label for page in pdf.pages]
```

What's in the table of contents?

```python
for entry in pdf.outlines:
    ...
```

If you are lucky it has a "logical structure tree".  The elements here
might even be referenced from the table of contents!  (or, they might
not... with PDF you never know)

```python
structure = pdf.structtree
for element in structure:
   for child in element:
       ...
```

Now perhaps we want to look at a specific page.  Okay!
```python
page = pdf.pages[0]        # they are numbered from 0
page = pdf.pages["xviii"]  # but you can get them by label
page = pdf.pages["42"]  # or "logical" page number (also a label)
a_few_content_streams = list(page.contents)
raw_bytes = b"".join(stream.buffer for stream in page.contents)
```

This page probably has text, graphics, etc, etc, in it.  Remember that
**P**LAYA ain't a **LAY**out **A**nalyzer!  You can either look at the
stream of tokens or mysterious PDF objects:
```python
for token in page.tokens:
    ...
for object in page:
    ...
```

Or you can access individual characters, lines, curves, and rectangles
(if you wanted to, for instance, do layout analysis):
```python
for item in page.layout:
    ...
```

Do we make you spelunk in a dank class hierarchy to know what these
items are?  No, we do not! They are just NamedTuples with a very
helpful field *telling* you what they are, as a string.

In particular you can also extract all these items into a dataframe
using the library of your choosing (I like [Polars]()) and I dunno do
some Artifishul Intelligents or something with them:
```python
```

Or just write them to a CSV file:
```python
```

Note again that PLAYA doesn't guarantee that these characters come at
you in anything other than the order they occur in the file (but it
does guarantee that).  It does, however, put them in (hopefully) the
right absolute positions on the page, and keep track of the clipping
path and the graphics state, so yeah, you *could* "render" them like
`pdfminer.six` pretended to do.

Certain PDF tools and/or authors are notorious for using "whiteout"
(set the color to the background color) or "scissors" (the clipping
path) to hide arbitrary text that maybe *you* don't want to see
either. PLAYA gives you some rudimentary tools to detect this:
```python
```

For everything else, there's pdfplumber, pdfium2, pikepdf, pypdf,
borb, pydyf, etc, etc, etc.

## Acknowledgement

This repository obviously includes code from `pdfminer.six`.  Original
license text is included in [LICENSE](/LICENSE.pdfminer).  The license
itself has not changed!
