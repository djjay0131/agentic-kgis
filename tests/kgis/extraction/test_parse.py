"""Structured-output parsing: shapes accepted, malformed output isolated."""

from __future__ import annotations

import pytest

from kgis.extraction.parse import ExtractionParseError, JsonItemsParser


def test_parses_items_object() -> None:
    items = JsonItemsParser().parse('{"items": [{"player_id": "1", "name": "Ada"}]}')
    assert len(items) == 1
    assert items[0].values == {"player_id": "1", "name": "Ada"}
    assert items[0].confidence is None


def test_parses_bare_array() -> None:
    items = JsonItemsParser().parse('[{"a": 1}, {"b": 2}]')
    assert [i.values for i in items] == [{"a": 1}, {"b": 2}]


def test_lifts_confidence_out_of_values() -> None:
    items = JsonItemsParser().parse('{"items": [{"player_id": "1", "confidence": 0.8}]}')
    assert items[0].confidence == 0.8
    assert "confidence" not in items[0].values


def test_extraction_confidence_alias_is_lifted() -> None:
    items = JsonItemsParser().parse('[{"x": 1, "extraction_confidence": 0.3}]')
    assert items[0].confidence == 0.3
    assert items[0].values == {"x": 1}


def test_non_json_raises_parse_error() -> None:
    with pytest.raises(ExtractionParseError, match="not valid JSON"):
        JsonItemsParser().parse("not json at all")


def test_object_without_items_raises() -> None:
    with pytest.raises(ExtractionParseError, match="items"):
        JsonItemsParser().parse('{"players": []}')


def test_scalar_item_raises() -> None:
    with pytest.raises(ExtractionParseError, match="must be an object"):
        JsonItemsParser().parse('{"items": ["just a string"]}')


def test_non_numeric_confidence_raises() -> None:
    with pytest.raises(ExtractionParseError, match="must be a number"):
        JsonItemsParser().parse('{"items": [{"confidence": "high"}]}')


def test_out_of_range_confidence_raises() -> None:
    # ExtractedItem validates 0..1; a value outside the range is a data fault.
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        JsonItemsParser().parse('{"items": [{"confidence": 1.5}]}')


def test_empty_items_yields_no_items() -> None:
    assert JsonItemsParser().parse('{"items": []}') == []


class TestQuote:
    """Per-item quotes are verified against the chunk; paraphrases are dropped."""

    CHUNK = "Ada is a shortstop known for hitting."
    OFFSET = 100

    def test_verified_quote_is_lifted_with_document_offsets(self) -> None:
        items = JsonItemsParser().parse(
            '{"items": [{"player_id": "ada", "quote": "shortstop"}]}',
            chunk_text=self.CHUNK,
            chunk_start=self.OFFSET,
        )
        item = items[0]
        assert item.quote == "shortstop"
        assert item.quote_start == self.OFFSET + self.CHUNK.index("shortstop")
        assert item.quote_end == item.quote_start + len("shortstop")
        assert self.CHUNK[item.quote_start - self.OFFSET:item.quote_end - self.OFFSET] == "shortstop"
        assert "quote" not in item.values
        assert item.warnings == ()

    def test_non_substring_quote_is_dropped_with_a_warning(self) -> None:
        items = JsonItemsParser().parse(
            '{"items": [{"player_id": "ada", "quote": "a pitcher"}]}',
            chunk_text=self.CHUNK,
        )
        item = items[0]
        assert item.quote is None
        assert item.quote_start is None and item.quote_end is None
        assert any("not an exact substring" in w for w in item.warnings)
        assert "quote" not in item.values  # never leaks into the candidate values

    def test_non_string_quote_is_dropped_with_a_warning(self) -> None:
        items = JsonItemsParser().parse(
            '{"items": [{"x": 1, "quote": 5}]}', chunk_text=self.CHUNK
        )
        assert items[0].quote is None
        assert any("must be a string" in w for w in items[0].warnings)

    def test_empty_quote_is_dropped_with_a_warning(self) -> None:
        items = JsonItemsParser().parse(
            '{"items": [{"x": 1, "quote": ""}]}', chunk_text=self.CHUNK
        )
        assert items[0].quote is None
        assert any("empty" in w for w in items[0].warnings)

    def test_quote_without_chunk_text_is_dropped_not_assumed(self) -> None:
        # No chunk text supplied: nothing can be verified, so the quote is
        # dropped rather than trusted (never store an unverified quote).
        items = JsonItemsParser().parse('{"items": [{"x": 1, "quote": "shortstop"}]}')
        assert items[0].quote is None
        assert items[0].warnings

    def test_verification_uses_the_first_occurrence(self) -> None:
        text = "Yes yes yes"
        items = JsonItemsParser().parse(
            '{"items": [{"x": 1, "quote": "yes"}]}', chunk_text=text
        )
        assert items[0].quote_start == 4  # deterministic, first occurrence

    def test_repeated_quotes_anchor_to_successive_occurrences(self) -> None:
        # Two (or more) items quoting the same text must not collapse onto the
        # first occurrence: each gets its own span so each gets its own evidence
        # id downstream.
        text = "Paris to Paris to Paris"
        items = JsonItemsParser().parse(
            '{"items": [{"id": 1, "quote": "Paris"}, '
            '{"id": 2, "quote": "Paris"}, {"id": 3, "quote": "Paris"}]}',
            chunk_text=text,
        )
        assert [i.quote_start for i in items] == [0, 9, 18]
        assert [i.quote_end for i in items] == [5, 14, 23]
        assert all(i.quote == "Paris" for i in items)
        assert all(i.warnings == () for i in items)

    def test_repeated_quote_beyond_occurrences_falls_back_to_the_first(self) -> None:
        # A quote that out-numbers its occurrences still verifies; it re-anchors
        # to the first rather than being dropped.
        text = "yes and yes"
        items = JsonItemsParser().parse(
            '{"items": [{"id": 1, "quote": "yes"}, {"id": 2, "quote": "yes"}, '
            '{"id": 3, "quote": "yes"}]}',
            chunk_text=text,
        )
        assert [i.quote_start for i in items] == [0, 8, 0]
        assert all(i.quote == "yes" for i in items)

    def test_used_offsets_do_not_leak_across_parse_calls(self) -> None:
        # The used-offset set is per-parse, not per-parser: reusing one parser
        # instance for a second chunk must anchor from that chunk's first
        # occurrence again.
        parser = JsonItemsParser()
        first = parser.parse(
            '{"items": [{"x": 1, "quote": "yes"}]}', chunk_text="yes yes"
        )
        second = parser.parse(
            '{"items": [{"x": 2, "quote": "yes"}]}', chunk_text="yes yes"
        )
        assert first[0].quote_start == 0
        assert second[0].quote_start == 0

    def test_differing_whitespace_fails_closed(self) -> None:
        # Exact matching: no whitespace normalisation, so a quote with different
        # spacing is not verified.
        items = JsonItemsParser().parse(
            '{"items": [{"x": 1, "quote": "Ada  is"}]}',
            chunk_text="Ada is a shortstop.",
        )
        assert items[0].quote is None
        assert any("not an exact substring" in w for w in items[0].warnings)
