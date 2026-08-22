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
