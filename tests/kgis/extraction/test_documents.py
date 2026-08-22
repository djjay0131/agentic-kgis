"""Document sources and chunkers: stable, resolvable, repeatable coordinates."""

from __future__ import annotations

from kgis.extraction.documents import (
    Document,
    FixedWindowChunker,
    IterableDocumentSource,
    ParagraphChunker,
    WholeDocumentChunker,
)


def test_iterable_source_is_repeatable() -> None:
    source = IterableDocumentSource([Document(doc_id="a", text="x"), Document(doc_id="b", text="y")])
    first = [d.doc_id for d in source.documents()]
    second = [d.doc_id for d in source.documents()]
    assert first == second == ["a", "b"]


def test_whole_document_chunker_single_chunk() -> None:
    doc = Document(doc_id="d", text="hello world")
    chunks = WholeDocumentChunker().chunk(doc)
    assert len(chunks) == 1
    assert chunks[0].text == "hello world"
    assert chunks[0].start == 0
    assert chunks[0].end == len("hello world")


def test_paragraph_chunker_offsets_resolve_to_source() -> None:
    doc = Document(doc_id="d", text="First para.\n\nSecond para here.")
    chunks = ParagraphChunker().chunk(doc)
    assert [c.text for c in chunks] == ["First para.", "Second para here."]
    # The offsets must slice the ORIGINAL text back to the chunk text.
    for chunk in chunks:
        assert doc.text[chunk.start : chunk.end] == chunk.text


def test_paragraph_chunker_skips_blank_paragraphs() -> None:
    doc = Document(doc_id="d", text="A\n\n\n\nB")
    chunks = ParagraphChunker().chunk(doc)
    assert [c.text for c in chunks] == ["A", "B"]
    assert [c.index for c in chunks] == [0, 1]


def test_fixed_window_chunker_covers_text_with_overlap() -> None:
    doc = Document(doc_id="d", text="abcdefghij")
    chunks = FixedWindowChunker(window=4, overlap=1).chunk(doc)
    # windows step by 3: [0:4], [3:7], [6:10] — the last fully covers the tail,
    # so no redundant trailing sliver is emitted.
    assert [c.text for c in chunks] == ["abcd", "defg", "ghij"]
    for chunk in chunks:
        assert doc.text[chunk.start : chunk.end] == chunk.text


def test_chunker_is_repeatable_and_coordinates_stable() -> None:
    doc = Document(doc_id="d", text="First.\n\nSecond.")
    a = ParagraphChunker().chunk(doc)
    b = ParagraphChunker().chunk(doc)
    assert [c.coordinates for c in a] == [c.coordinates for c in b]


def test_fragment_encodes_index_and_span() -> None:
    doc = Document(doc_id="d", text="First.\n\nSecond.")
    chunks = ParagraphChunker().chunk(doc)
    assert chunks[0].fragment == "chunk:0@chars:0-6"
    assert chunks[1].coordinates.fragment == chunks[1].fragment


def test_chunk_coordinates_carry_document_source_type_and_locator() -> None:
    doc = Document(doc_id="d", text="hi", source_type="pdf", locator="file:///d.pdf")
    chunk = WholeDocumentChunker().chunk(doc)[0]
    assert chunk.coordinates.source_type == "pdf"
    assert chunk.coordinates.locator == "file:///d.pdf"


def test_document_locator_defaults_to_doc_id() -> None:
    assert Document(doc_id="d", text="x").resolved_locator == "d"
    assert Document(doc_id="d", text="x", locator="u").resolved_locator == "u"
