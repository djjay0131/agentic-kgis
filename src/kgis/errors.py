"""`kgis` exception types.

Deliberately few. Rejections are **data**, not exceptions (spec §9): a
malformed record produces a `RecordIssue` and a validation failure in the
`IngestionReport`, never a raised exception. An exception here means a bug
or an infrastructure fault — something that stops the *run*, not something
that stops a *record*.

`SourceReadError` is the one boundary where the distinction bites: an I/O
fault mid-stream is not the record's fault, so the pipeline catches it,
marks the report `incomplete=True` (never a silent truncation), and keeps
the candidates it already built.
"""


class KgisError(Exception):
    """Base class for every error raised by `kgis`."""


class SourceReadError(KgisError):
    """A source could not be read, or failed part-way through the stream.

    Raised by `RecordReader` implementations for I/O and parse faults (an
    unreadable file, malformed JSON, a truncated CSV). The pipeline treats
    this as a `TRANSIENT_FAULT`: the run is marked incomplete and reports a
    partial result — a failed read must never look like an empty source.
    """


class ConfigurationError(KgisError):
    """A pipeline was assembled with incoherent configuration.

    Raised at construction, not at run time — e.g. a builder pointing at a
    field the normalizer never produces. This is a wiring bug: it should
    fail loudly before any data is touched, never silently emit zero
    candidates.
    """
