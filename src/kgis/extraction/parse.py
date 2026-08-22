"""Structured-output parsing: raw model text → validated `ExtractedItem`s.

A model returns a string; a builder needs fields. This module is the seam
between them, and its one hard rule is that **malformed model output is
isolated, never fatal**: `parse()` raises `ExtractionParseError`, which the
runner catches per (extractor, chunk) so one hallucinated non-JSON response
cannot take down the run or its successful siblings.

The default `JsonItemsParser` accepts either a bare JSON array of objects or
an object with an `"items"` array, and lifts a per-item `confidence` (or
`extraction_confidence`) out of the field bag: model-reported extraction
confidence is a first-class, orthogonal score (ADR-0004), not just another
attribute to be built into a candidate. Everything else in the object becomes
the record `values` a `CandidateBuilder` consumes — so the same builders that
serve structured sync serve extraction, with the LLM only supplying the rows.
"""

from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class ExtractionParseError(ValueError):
    """Model output could not be parsed into structured items.

    A data fault attributable to the model's response, not a bug: the runner
    turns it into a reported per-extractor failure, isolating it from sibling
    extractors and documents (spec §9).
    """


class ExtractedItem(BaseModel):
    """One structured record lifted from a model response.

    `values` are the fields a `CandidateBuilder` will consume — exactly the
    shape a `NormalizedRecord` carries. `confidence` is the model's *reported*
    extraction confidence for this item, pulled out of the field bag because
    it belongs on the candidate's `extraction_confidence` score axis, not in
    its properties.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    values: dict[str, object]
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


@runtime_checkable
class OutputParser(Protocol):
    """Turns one raw model response into zero or more `ExtractedItem`s.

    Raises `ExtractionParseError` on malformed output — never returns a
    partial or invented result.
    """

    def parse(self, raw: str) -> list[ExtractedItem]: ...


_CONFIDENCE_KEYS = ("confidence", "extraction_confidence")


class JsonItemsParser:
    """Parses `{"items": [ {...}, ... ]}` or a bare `[ {...}, ... ]`.

    Each object becomes an `ExtractedItem`: a `confidence`/`extraction_confidence`
    field (if present) is lifted onto the item's score, and the remaining keys
    become `values`. A non-JSON response, a non-object item, or a confidence
    outside `[0, 1]` is an `ExtractionParseError`.
    """

    def parse(self, raw: str) -> list[ExtractedItem]:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ExtractionParseError(f"response is not valid JSON: {exc}") from exc

        if isinstance(payload, dict):
            raw_items = payload.get("items")
            if raw_items is None:
                raise ExtractionParseError(
                    "object response must carry an 'items' array"
                )
        elif isinstance(payload, list):
            raw_items = payload
        else:
            raise ExtractionParseError(
                f"response must be a JSON array or an object with 'items', "
                f"got {type(payload).__name__}"
            )

        if not isinstance(raw_items, list):
            raise ExtractionParseError("'items' must be an array")

        items: list[ExtractedItem] = []
        for position, entry in enumerate(raw_items):
            if not isinstance(entry, dict):
                raise ExtractionParseError(
                    f"item {position} must be an object, got {type(entry).__name__}"
                )
            values = {str(key): value for key, value in entry.items()}
            confidence = self._pop_confidence(values, position)
            items.append(ExtractedItem(values=values, confidence=confidence))
        return items

    def _pop_confidence(self, values: dict[str, object], position: int) -> float | None:
        for key in _CONFIDENCE_KEYS:
            if key in values:
                raw_value = values.pop(key)
                if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
                    raise ExtractionParseError(
                        f"item {position} {key!r} must be a number, "
                        f"got {type(raw_value).__name__}"
                    )
                return float(raw_value)
        return None
