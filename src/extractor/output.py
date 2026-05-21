"""Write extracted claims to the workstream-B output CSV.

The CSV is the contract handed to workstream C (verification) and workstream D
(labeling): one row per claim, columns in ``schema.CSV_FIELDS`` order.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path

from extractor.schema import CSV_FIELDS, Claim


def _cell(value) -> str:
    """Render one field value as a CSV cell."""
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def write_claims_csv(claims: Iterable[Claim], path: str | Path) -> Path:
    """Write ``claims`` to ``path`` as CSV. Creates parent directories.

    Returns the resolved output path.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CSV_FIELDS))
        writer.writeheader()
        for claim in claims:
            dumped = claim.model_dump()
            writer.writerow({field: _cell(dumped[field]) for field in CSV_FIELDS})
    return path
