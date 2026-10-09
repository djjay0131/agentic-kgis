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

Quote verification is **exact**. There is no Unicode or whitespace
normalisation (no NFC/NFKC folding, no collapse/trim of interior or boundary
whitespace): a quote is stored only if `chunk_text.find(quote) >= 0` on the
raw strings. Any difference — a curly apostrophe for a straight one, a
non-breaking space for a space, a different number of spaces — fails closed as
`quote_not_verified` and the quote is dropped. This is deliberate: a
normalising matcher can silently widen a quote's meaning, and a dropped quote
is honest where a mangled one is not.

Two items that quote the same text are anchored to **successive occurrences**
within the chunk (a per-parse set of used offsets), so each gets its own
document span and its own evidence id instead of collapsing onto the first
occurrence. Only when every occurrence is already claimed does an item fall
back to the first, so a repeated quote still verifies rather than being
dropped.
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

    **Custom parser authors:** `chunk_text`/`chunk_start` were added to this
    protocol in the same release as the typed-span work (ADR candidate 0011,
    which also bumps `CONTRACT_VERSION` `2.1.0 -> 2.2.0`). They are keyword-only
    and defaulted, so existing callers keep working, but a custom
    `OutputParser` implementation must accept `chunk_text` and `chunk_start`
    (even if it ignores them) or the runner's `parse(raw, chunk_text=...,
    chunk_start=...)` call will raise `TypeError`.

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
        used_quote_offsets: set[int] = set()
        for position, entry in enumerate(raw_items):
            if not isinstance(entry, dict):
                raise ExtractionParseError(
                    f"item {position} must be an object, got {type(entry).__name__}"
                )
            values = {str(key): value for key, value in entry.items()}
            confidence = self._pop_confidence(values, position)
            quote, quote_start, quote_end, warnings = self._pop_quote(
                values,
                position,
                chunk_text=chunk_text,
                chunk_start=chunk_start,
                used_offsets=used_quote_offsets,
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
        used_offsets: set[int],
    ) -> tuple[str | None, int | None, int | None, tuple[str, ...]]:
        """Lift `quote` out of `values`, verifying it is an exact chunk substring.

        Returns `(quote, start, end, warnings)`. On any failure the quote is
        dropped (`None`) and a warning is returned instead — a paraphrase must
        never be recorded as a verbatim quote.

        Matching is **exact** on the raw strings: no Unicode or whitespace
        normalisation is applied, so any byte-level difference fails closed.

        `used_offsets` is the set of chunk-local offsets already anchored in
        **this** parse. A repeated quote is anchored to the next *unused*
        occurrence, so two items quoting the same text get distinct document
        spans (and therefore distinct evidence ids) rather than collapsing onto
        the first occurrence. Only when every occurrence is already claimed does
        the item fall back to the first, so a quote that out-numbers its
        occurrences still verifies rather than being dropped.
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
        local = self._next_unused_offset(chunk_text, raw_quote, used_offsets)
        if local < 0:
            return None, None, None, (
                f"item {position} quote is not an exact substring of the chunk "
                f"text; quote dropped",
            )
        used_offsets.add(local)
        start = chunk_start + local
        return raw_quote, start, start + len(raw_quote), ()

    @staticmethod
    def _next_unused_offset(chunk_text: str, quote: str, used_offsets: set[int]) -> int:
        """The next occurrence of `quote` not in `used_offsets`, else the first.

        Returns `-1` when `quote` is not an occurrence at all. Scans from each
        match's `+1` so overlapping occurrences are distinct anchors.
        """
        search_from = 0
        while True:
            found = chunk_text.find(quote, search_from)
            if found < 0:
                break
            if found not in used_offsets:
                return found
            search_from = found + 1
        return chunk_text.find(quote)
