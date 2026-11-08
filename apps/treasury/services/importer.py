import csv
import datetime as dt
import io
import os
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook

from apps.activity.services.events import record_event
from ..models import ImportBatch, ProjectGroup, TreasuryEntry
from ..types import CATEGORIES_BY_DIRECTION, Category, Direction
from .errors import TreasuryError
from .ledger import parse_amount, reverse_entry

MAX_ROWS = 500
FIELDS = ("date", "amount", "details", "category", "group")
REQUIRED = ("date", "amount", "details")


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, (dt.date, dt.datetime)):
        return value
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _iter_raw(file):
    ext = os.path.splitext(getattr(file, "name", "") or "")[1].lower()
    if ext == ".xlsx":
        try:
            wb = load_workbook(file, read_only=True, data_only=True)
            yield from wb.worksheets[0].iter_rows(values_only=True)
        except TreasuryError:
            raise
        except Exception:
            raise TreasuryError("invalid_file", "Could not read the spreadsheet.")
    elif ext == ".csv":
        try:
            yield from csv.reader(io.TextIOWrapper(file, encoding="utf-8-sig", newline=""))
        except (UnicodeDecodeError, csv.Error):
            raise TreasuryError("invalid_file", "Could not read the CSV file.")
    else:
        raise TreasuryError("invalid_file", "Only .xlsx and .csv files are supported.")


def parse_sheet(file) -> list:
    raw = _iter_raw(file)
    header = next(raw, None)
    names = [str(h).strip().lower() if h is not None else "" for h in (header or [])]
    if any(f not in names for f in REQUIRED):
        raise TreasuryError("invalid_file", "Header must include date, amount and details columns.")
    idx = {f: names.index(f) for f in FIELDS if f in names}
    rows = []
    for r in raw:
        row = {f: (_cell(r[i]) if i < len(r) else "") for f, i in idx.items()}
        for f in FIELDS:
            row.setdefault(f, "")
        if not any(row.values()):
            continue
        if len(rows) >= MAX_ROWS:
            raise TreasuryError("too_many_rows", f"At most {MAX_ROWS} rows are allowed.")
        rows.append(row)
    return rows


def _parse_date(value):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.datetime.strptime(str(value).strip(), "%Y-%m-%d").date()


def validate_rows(rows, default_group: Optional[ProjectGroup]) -> tuple:
    groups = {g.name.lower(): g for g in ProjectGroup.objects.all()}
    clean, errors = [], []
    for n, r in enumerate(rows, start=1):
        bad = []

        def err(field, message):
            bad.append({"row": n, "field": field, "message": message})

        d = amount = None
        try:
            d = _parse_date(r.get("date", ""))
            if d > dt.date.today():
                err("date", "Date cannot be in the future.")
        except (ValueError, TypeError):
            err("date", "Date must be YYYY-MM-DD.")
        try:
            amount = parse_amount(r.get("amount", ""))
        except TreasuryError as e:
            err("amount", e.message)
        details = r.get("details", "")
        details = details.strip() if isinstance(details, str) else ""
        if not 1 <= len(details) <= 250:
            err("details", "Details must be 1-250 characters.")
        category = str(r.get("category") or "").strip().lower() or Category.OPERATING
        if category == Category.ADVANCE or category not in CATEGORIES_BY_DIRECTION[Direction.OUT]:
            err("category", "Category must be operating or other.")
        gname = str(r.get("group") or "").strip()
        group = default_group
        if gname:
            group = groups.get(gname.lower())
            if group is None:
                err("group", "Unknown group.")
        if bad:
            errors.extend(bad)
        else:
            clean.append({"date": d, "amount": amount, "details": details,
                          "category": str(category), "group": group})
    return clean, errors


@transaction.atomic
def import_rows(by, rows, default_group) -> ImportBatch:
    clean, errors = validate_rows(rows, default_group)
    if errors:
        raise TreasuryError("invalid", "The sheet has invalid rows.", errors=errors)
    if not clean:
        raise TreasuryError("invalid", "The sheet has no rows.")
    batch = ImportBatch.objects.create(created_by=by, row_count=len(clean))
    TreasuryEntry.objects.bulk_create([
        TreasuryEntry(direction=Direction.OUT, category=c["category"], amount=c["amount"],
                      date=c["date"], details=c["details"], group=c["group"],
                      created_by=by, import_batch=batch)
        for c in clean])
    total = sum((c["amount"] for c in clean), Decimal(0))
    record_event(by, "import.done", target=batch, label=f"{len(clean)} rows",
                 data={"count": len(clean), "total": f"{total:.2f}"})
    return batch


@transaction.atomic
def reverse_batch(by, batch, reason) -> ImportBatch:
    reason = reason.strip() if isinstance(reason, str) else ""
    if not reason:
        raise TreasuryError("invalid", "A reason is required.")
    batch = ImportBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.reversed_at is not None:
        raise TreasuryError("already_reversed", "This batch is already reversed.")
    entries = list(TreasuryEntry.objects.select_for_update().filter(import_batch=batch))
    if any(e.reversed_at is not None for e in entries):
        raise TreasuryError("partially_reversed", "Some entries were already reversed individually.")
    for e in entries:
        reverse_entry(by, e, reason, emit=False)
    batch.reversed_at = timezone.now()
    batch.reversed_by = by
    batch.reversal_reason = reason
    batch.save(update_fields=["reversed_at", "reversed_by", "reversal_reason", "updated_at"])
    record_event(by, "import.reversed", target=batch, label=f"{len(entries)} rows",
                 data={"count": len(entries), "reason": reason})
    return batch
