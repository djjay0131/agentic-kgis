"""Source readers: the pipeline's I/O edge (spec §6).

Every source is uniform behind `RecordReader` — the pipeline cannot tell a
CSV file from a list of dicts, which is exactly why a test and production
exercise the same code path. Databases are deliberately absent in Sprint 1.
"""

from kgis.sources.base import RecordReader
from kgis.sources.csv_reader import UNNAMED_COLUMNS, CsvRecordReader
from kgis.sources.iterable_reader import IterableRecordReader
from kgis.sources.json_reader import JsonMode, JsonRecordReader

__all__ = [
    "UNNAMED_COLUMNS",
    "CsvRecordReader",
    "IterableRecordReader",
    "JsonMode",
    "JsonRecordReader",
    "RecordReader",
]
