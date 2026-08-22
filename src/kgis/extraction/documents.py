"""Document/chunk source abstraction with *stable source coordinates*.

LLM extraction reads free text, not rows, so it needs its own front-end
before the shared candidate machinery: a `Document` is loaded, a `Chunker`
segments it into `Chunk`s, and each chunk carries a `SourceCoordinates` that
pins it to the exact span of the exact document it came from. Those
coordinates are the idempotency anchor (spec §5.8) for everything built
downstream — so they must be **repeatable**: re-loading the same document and
re-chunking it with the same chunker must yield byte-identical coordinates,
or two ingests of one document would look like two different sets of facts.

The chunk's `fragment` therefore encodes *both* the ordinal chunk index and
its character span (`chunk:2@chars:180-240`): the index keeps sibling chunks
distinct even if two happen to share text, and the span makes the coordinate
resolvable back to the source without re-running the chunker. A `Chunker` is
a pure function of the document — no clock, no randomness — for the same
reason `RecordReader.read()` must be repeatable (`sources/base.py`).

Like `RecordReader`, a `DocumentSource.documents()` is repeatable: the
pipeline may `plan()` then `run()` over the same source, and a one-shot
generator would make the second pass silently see an empty corpus.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from kg_contracts.candidates import SourceCoordinates


def _blake2b(text: str) -> str:
    """A stable content hash — change detection, never an identity anchor."""
    return "b2:" + hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()


class Document(BaseModel):
    """One source document, before any segmentation or extraction.

    `doc_id` is the stable identity of the document within its corpus and
    becomes the `locator` of every chunk's coordinates. `locator` may name a
    physical origin (a URI, a path) distinct from `doc_id`; it defaults to
    `doc_id` when the two coincide.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str = Field(min_length=1)
    text: str
    source_type: str = "document"
    locator: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @property
    def resolved_locator(self) -> str:
        """The document's locator, falling back to `doc_id`."""
        return self.locator if self.locator is not None else self.doc_id

    @property
    def content_hash(self) -> str:
        return _blake2b(self.text)


class Chunk(BaseModel):
    """A contiguous span of one document, with a stable, resolvable locator.

    `start`/`end` are character offsets into the *source document*, not the
    chunk — so `document.text[start:end] == text` for any chunker that does
    not transform the text it slices. That is what makes `fragment`
    resolvable: an operator (or a later re-collection) can find the exact
    passage from the coordinate alone.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str = Field(min_length=1)
    index: int = Field(ge=0)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str
    source_type: str = "document"
    locator: str = Field(min_length=1)

    @property
    def fragment(self) -> str:
        """The chunk's stable in-document locator: index *and* char span.

        Both halves matter: the span makes it resolvable back to the source,
        and the index keeps two chunks distinct even in the pathological case
        where they share identical text and offsets would collide.
        """
        return f"chunk:{self.index}@chars:{self.start}-{self.end}"

    @property
    def coordinates(self) -> SourceCoordinates:
        """The idempotency anchor for everything extracted from this chunk."""
        return SourceCoordinates(
            source_type=self.source_type, locator=self.locator, fragment=self.fragment
        )

    @property
    def content_hash(self) -> str:
        return _blake2b(self.text)


@runtime_checkable
class DocumentSource(Protocol):
    """Loads documents from one corpus (the extraction analogue of `RecordReader`).

    `documents()` must be **repeatable**: calling it twice yields equal
    documents both times, so a dry-run followed by an execution reads the same
    corpus rather than an exhausted iterator.
    """

    @property
    def source_type(self) -> str: ...

    @property
    def locator(self) -> str:
        """Stable locator for the corpus as a whole — a directory, a dataset name."""
        ...

    def documents(self) -> Iterator[Document]: ...


class IterableDocumentSource:
    """A `DocumentSource` over an in-memory sequence of documents.

    Materializes its documents into a tuple at construction so `documents()`
    is repeatable however the caller supplied them (a list, a generator).
    """

    def __init__(
        self,
        documents: Sequence[Document],
        *,
        source_type: str = "document",
        locator: str = "memory",
    ) -> None:
        self._documents = tuple(documents)
        self._source_type = source_type
        self._locator = locator

    @property
    def source_type(self) -> str:
        return self._source_type

    @property
    def locator(self) -> str:
        return self._locator

    def documents(self) -> Iterator[Document]:
        return iter(self._documents)


@runtime_checkable
class Chunker(Protocol):
    """Segments one document into chunks — a *pure* function of the document.

    No clock, no randomness, no state: the same document must always produce
    the same chunks, because those chunks' coordinates are idempotency anchors.
    """

    def chunk(self, document: Document) -> list[Chunk]: ...


class WholeDocumentChunker:
    """One chunk per document — the whole text as a single passage.

    The right choice for short documents an extractor can read in one pass,
    and the simplest coordinate to reason about (`chunk:0@chars:0-<len>`).
    """

    def chunk(self, document: Document) -> list[Chunk]:
        return [
            Chunk(
                doc_id=document.doc_id,
                index=0,
                start=0,
                end=len(document.text),
                text=document.text,
                source_type=document.source_type,
                locator=document.resolved_locator,
            )
        ]


class ParagraphChunker:
    """Splits on blank-line boundaries, preserving true character offsets.

    Blank runs are the separator, not content, so they are skipped — but the
    offsets carried on each chunk are still offsets into the *original* text,
    so `document.text[chunk.start:chunk.end] == chunk.text`. Empty paragraphs
    produce no chunk.
    """

    def chunk(self, document: Document) -> list[Chunk]:
        text = document.text
        chunks: list[Chunk] = []
        cursor = 0
        length = len(text)
        index = 0
        while cursor < length:
            # Find the next blank-line boundary ("\n\n") after the cursor.
            boundary = text.find("\n\n", cursor)
            end = length if boundary == -1 else boundary
            segment = text[cursor:end]
            stripped = segment.strip()
            if stripped:
                lead = len(segment) - len(segment.lstrip())
                trail = len(segment) - len(segment.rstrip())
                start = cursor + lead
                chunks.append(
                    Chunk(
                        doc_id=document.doc_id,
                        index=index,
                        start=start,
                        end=end - trail,
                        text=stripped,
                        source_type=document.source_type,
                        locator=document.resolved_locator,
                    )
                )
                index += 1
            if boundary == -1:
                break
            cursor = boundary + 2
        return chunks


class FixedWindowChunker:
    """Fixed-width character windows, optionally overlapping.

    Deterministic and format-agnostic: it knows nothing about sentences, only
    offsets, which keeps its coordinates trivially stable. `overlap` lets a
    fact straddling a window boundary still land wholly inside one chunk.
    """

    def __init__(self, *, window: int, overlap: int = 0) -> None:
        if window < 1:
            raise ValueError("window must be >= 1")
        if overlap < 0 or overlap >= window:
            raise ValueError("overlap must satisfy 0 <= overlap < window")
        self._window = window
        self._overlap = overlap

    def chunk(self, document: Document) -> list[Chunk]:
        text = document.text
        length = len(text)
        if length == 0:
            return []
        step = self._window - self._overlap
        chunks: list[Chunk] = []
        index = 0
        start = 0
        while start < length:
            end = min(start + self._window, length)
            chunks.append(
                Chunk(
                    doc_id=document.doc_id,
                    index=index,
                    start=start,
                    end=end,
                    text=text[start:end],
                    source_type=document.source_type,
                    locator=document.resolved_locator,
                )
            )
            index += 1
            if end >= length:
                break
            start += step
        return chunks
