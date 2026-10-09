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
attribute to be built into a candidate. It also lifts an optional per-item
`quote`, but only after verifying it is an exact substring of the chunk — the
document offsets are computed from the chunk, and a non-substring quote is
dropped with a warning rather than stored as a paraphrase (ADR candidate 0011).
Everything else in the object becomes the record `values` a `CandidateBuilder`
consumes — so the same builders that serve structured sync serve extraction,
with the LLM only supplying the rows.
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

    `quote` is the model-reported source text supporting the item. It is set
    **only after** the parser verified it is an exact substring of the chunk:
    a paraphrase is never stored as a quote. `quote_start`/`quote_end` are the
    corresponding *document* offsets (chunk offset + local index). `warnings`
    records non-fatal parse notes, chiefly a quote that failed verification.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    values: dict[str, object]
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    quote: str | None = None
    quote_start: int | None = Field(default=None, ge=0)
    quote_end: int | None = Field(default=None, ge=0)
    warnings: tuple[str, ...] = ()


@runtime_checkable
class OutputParser(Protocol):
    """Turns one raw model response into zero or more `ExtractedItem`s.

    `chunk_text`/`chunk_start` locate the chunk the response describes, so a
    parser that lifts a per-item `quote` can verify it against the chunk and
    compute document offsets. They default to an empty chunk at offset 0, which
    is right for a caller that does not deal in quotes.

    Raises `ExtractionParseError` on malformed output — never returns a
    partial or invented result.
    """

    def parse(
        self, raw: str, *, chunk_text: str = "", chunk_start: int = 0
    ) -> list[ExtractedItem]: ...


_CONFIDENCE_KEYS = ("confidence", "extraction_confidence")
_QUOTE_KEY = "quote"


class JsonItemsParser:
    """Parses `{"items": [ {...}, ... ]}` or a bare `[ {...}, ... ]`.

    Each object becomes an `ExtractedItem`: a `confidence`/`extraction_confidence`
    field (if present) is lifted onto the item's score, a `quote` field (if
    present) is lifted onto the item's span once verified, and the remaining
    keys become `values`. A non-JSON response, a non-object item, or a
    confidence outside `[0, 1]` is an `ExtractionParseError`. A quote that is
    not an exact substring of the chunk is **dropped with a warning**, never
    stored as a paraphrase.
    """

    def parse(
        self, raw: str, *, chunk_text: str = "", chunk_start: int = 0
    ) -> list[ExtractedItem]:
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
            quote, quote_start, quote_end, warnings = self._pop_quote(
                values, position, chunk_text=chunk_text, chunk_start=chunk_start
            )
            items.append(
                ExtractedItem(
                    values=values,
                    confidence=confidence,
                    quote=quote,
                    quote_start=quote_start,
                    quote_end=quote_end,
                    warnings=warnings,
                )
            )
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

    def _pop_quote(
        self,
        values: dict[str, object],
        position: int,
        *,
        chunk_text: str,
        chunk_start: int,
    ) -> tuple[str | None, int | None, int | None, tuple[str, ...]]:
        """Lift `quote` out of `values`, verifying it is an exact chunk substring.

        Returns `(quote, start, end, warnings)`. On any failure the quote is
        dropped (`None`) and a warning is returned instead — a paraphrase must
        never be recorded as a verbatim quote.
        """
        if _QUOTE_KEY not in values:
            return None, None, None, ()
        raw_quote = values.pop(_QUOTE_KEY)
        if not isinstance(raw_quote, str):
            return None, None, None, (
                f"item {position} quote must be a string, "
                f"got {type(raw_quote).__name__}; quote dropped",
            )
        if not raw_quote:
            return None, None, None, (
                f"item {position} quote is empty; quote dropped",
            )
        local = chunk_text.find(raw_quote)
        if local < 0:
            return None, None, None, (
                f"item {position} quote is not an exact substring of the chunk "
                f"text; quote dropped",
            )
        start = chunk_start + local
        return raw_quote, start, start + len(raw_quote), ()
