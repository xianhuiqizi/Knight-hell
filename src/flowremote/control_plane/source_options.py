"""Validated, persisted source corrections and reusable business rules."""

from __future__ import annotations

import json
from dataclasses import replace

from flowremote.contracts.normalization import (
    BOX_TO_PIECE,
    MAPPED_FIELDS,
    REQUIRED_FIELDS,
    ColumnMapping,
    MappingResult,
)
from flowremote.control_plane.normalization import NormalizationError, build_mapping, detect_table


def options_for(file: dict) -> dict:
    return json.loads(file.get("options_json") or "{}")


def prepare_source(file: dict, data: bytes, options: dict | None = None):
    options = options_for(file) if options is None else options
    table = detect_table(file["filename"], data,
                         worksheet=options.get("worksheet") or None,
                         header_row=options.get("header_row") or None)
    try:
        mapping = build_mapping(table)
    except NormalizationError:
        if "columns" not in options:
            raise
        mapping = MappingResult(())
    if "columns" in options:
        columns = []
        used = set()
        for field, raw_index in options["columns"].items():
            if field not in MAPPED_FIELDS:
                raise NormalizationError("Unknown target field.")
            if str(raw_index) == "":
                continue
            try:
                index = int(raw_index)
            except (TypeError, ValueError) as exc:
                raise NormalizationError("Choose a source column for each field.") from exc
            if not 0 <= index < len(table.headers) or index in used:
                raise NormalizationError("A column is missing or mapped more than once.")
            used.add(index)
            columns.append(ColumnMapping(field, index, table.headers[index], 1.0,
                                         "human", ("User-selected source column",)))
        if set(REQUIRED_FIELDS) - {column.field for column in columns}:
            raise NormalizationError("Map every required field before saving.")
        mapping = replace(mapping, columns=tuple(columns))
    price = options.get("price_multiplier", "auto")
    if str(price) != "auto":
        if str(price) not in {"1", "1000"}:
            raise NormalizationError("Price multiplier must be 1 or 1000.")
        mapping = replace(mapping, price_multiplier=int(price))
    date_order = options.get("date_order", "auto")
    if date_order != "auto":
        if date_order not in {"day-first", "month-first"}:
            raise NormalizationError("Choose a supported date format.")
        mapping = replace(mapping, date_order=date_order)
    try:
        box_size = int(options.get("box_to_piece", BOX_TO_PIECE))
    except (TypeError, ValueError) as exc:
        raise NormalizationError("Pieces per box must be a positive integer.") from exc
    if not 1 <= box_size <= 100000:
        raise NormalizationError("Pieces per box must be between 1 and 100000.")
    return table, mapping, box_size
