"""CSV import service with deterministic normalization and idempotency."""

from __future__ import annotations

import csv
import datetime
import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List

from finance_app.extensions import db
from finance_app.lib.dates import _parse_date_tuple
from finance_app.models.accounting_models import CsvImportBatch, CsvImportRow, Transaction, TransactionJournalLink
from finance_app.services.account_service import ensure_account
from finance_app.services.journal_service import (
    JOURNAL_ERROR_INVALID_DC,
    JOURNAL_ERROR_UNBALANCED,
    JournalBalanceError,
    JournalLinePayload,
    create_journal_entry,
    map_journal_db_exception,
)
from finance_app.services.ml_service import record_suggestion_hint

ROW_DUPLICATE_BATCH = "duplicate_batch_file_sha256"
ROW_DUPLICATE_KEY = "duplicate_row_dedupe_key"
ROW_ERROR_NO_POSTABLE_LINES = "no_postable_lines"
ROW_ERROR_PARTIAL_DUPLICATE_GROUP = "partial_duplicate_group"
ROW_ERROR_UNBALANCED_JOURNAL = "unbalanced_journal"
ROW_ERROR_LEGACY_UNSUPPORTED_SHAPE = "legacy_unsupported_shape"
ROW_ERROR_INVALID_DC = "invalid_dc"

DEDUPE_VERSION = "v1"


@dataclass(frozen=True)
class ParsedCsvRow:
    row_number: int
    date_str: str
    date_parsed: datetime.date | None
    date_token: str
    description: str
    description_norm: str
    memo: str
    memo_norm: str
    currency: str
    debit_account: str
    credit_account: str
    debit_amount: Decimal
    credit_amount: Decimal
    external_txn_id: str | None
    row_sha256: str


@dataclass(frozen=True)
class CandidateLine:
    payload: JournalLinePayload
    row_number: int
    row_sha256: str
    row_dedupe_key: str
    external_txn_id: str | None
    account_id: int
    direction: str
    amount: Decimal
    currency: str
    effective_date: datetime.date | None
    counterparty_norm: str
    duplicate: bool


def _norm_key_dict(row: Dict[str, str]) -> Dict[str, str]:
    return {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}


def _get_any(d: Dict[str, str], keys: List[str], default: str = "") -> str:
    for k in keys:
        if k in d and d[k] != "":
            return d[k]
    return default


def _normalize_text(value: str | None) -> str:
    txt = re.sub(r"\s+", " ", (value or "").strip())
    return txt


def _normalize_text_lower(value: str | None) -> str:
    return _normalize_text(value).lower()


def _normalize_currency(value: str | None) -> str:
    return (_normalize_text(value).upper() or "KRW")


def _normalize_external_txn_id(value: str | None) -> str | None:
    txt = _normalize_text(value)
    return txt or None


def _safe_decimal(s: str) -> Decimal:
    try:
        cleaned = re.sub(r"[^0-9.\-]", "", (s or ""))
        if cleaned in ("", ".", "-", "-.", ".-"):
            return Decimal("0.00")
        return Decimal(cleaned).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


def _parse_date(raw: str) -> tuple[str, datetime.date | None, bool]:
    date_raw = raw or ""
    date_str = date_raw
    date_parsed = None
    parsed_ok = False
    if date_raw:
        try:
            date_obj = datetime.datetime.strptime(date_raw.replace("-", "/"), "%Y/%m/%d")
            date_str = date_obj.strftime("%Y/%m/%d")
            date_parsed = date_obj.date()
            parsed_ok = True
        except Exception:
            pass
        if not parsed_ok:
            y_raw, m_raw, d_raw = _parse_date_tuple(date_raw)
            try:
                if y_raw and m_raw and d_raw:
                    date_parsed = datetime.date(y_raw, m_raw, d_raw)
                    date_str = f"{y_raw}/{str(m_raw).zfill(2)}/{str(d_raw).zfill(2)}"
                    parsed_ok = True
            except Exception:
                date_parsed = None
    if not parsed_ok and date_str:
        y, m, d = _parse_date_tuple(date_str)
        try:
            if y and m and d:
                date_parsed = datetime.date(y, m, d)
                parsed_ok = True
        except Exception:
            date_parsed = None
    return date_str, date_parsed, parsed_ok


def _normalize_date_token(date_str: str, date_parsed: datetime.date | None) -> str:
    if date_parsed:
        return date_parsed.strftime("%Y/%m/%d")
    normalized = (date_str or "").strip().replace("-", "/")
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def _row_sha256(parsed: ParsedCsvRow) -> str:
    stable = "|".join(
        [
            DEDUPE_VERSION,
            parsed.date_token,
            parsed.description_norm,
            parsed.memo_norm,
            _normalize_text_lower(parsed.debit_account),
            _normalize_text_lower(parsed.credit_account),
            f"{parsed.debit_amount:.2f}",
            f"{parsed.credit_amount:.2f}",
            parsed.currency,
            parsed.external_txn_id or "",
        ]
    )
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def _row_dedupe_key(
    *,
    date_token: str,
    amount: Decimal,
    currency: str,
    counterparty_norm: str,
    account_id: int,
    direction: str,
    external_txn_id: str | None,
) -> str:
    parts = [
        DEDUPE_VERSION,
        f"date={date_token}",
        f"amount={amount:.2f}",
        f"currency={currency}",
        f"account_id={account_id}",
        f"direction={direction}",
    ]
    if external_txn_id:
        parts.append(f"external_txn_id={external_txn_id}")
    else:
        parts.append(f"counterparty={counterparty_norm}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _group_reference(key: str, rows: list[ParsedCsvRow]) -> str:
    external_txn_id = rows[0].external_txn_id
    if external_txn_id:
        return f"CSV:{external_txn_id}"[:120]
    merged = "|".join(sorted(row.row_sha256 for row in rows))
    digest = hashlib.sha256(merged.encode("utf-8")).hexdigest()[:32]
    return f"CSVROW:{digest}"[:120]


def _valid_write_mode(value: str | None) -> str:
    mode = (value or "journal").strip().lower()
    if mode not in {"journal", "dual", "legacy"}:
        return "journal"
    return mode


def _build_summary(
    *,
    batch_id: str,
    file_sha256: str,
    write_mode: str,
    rows_total: int,
    rows_new: int,
    rows_duplicate: int,
    rows_error: int,
    count_journal: int,
    count_simple: int,
    normalized_dates: int,
    unparsable_dates: int,
    duplicate_reasons: Counter,
    error_reasons: Counter,
    skipped_duplicate_batch: bool,
    skipped_unbalanced: list[str],
    skipped_existing: list[str],
) -> Dict[str, object]:
    summary = {
        "batch_id": batch_id,
        "file_sha256": file_sha256,
        "write_mode": write_mode,
        "skipped_duplicate_batch": skipped_duplicate_batch,
        "totals": {
            "rows_total": rows_total,
            "rows_new": rows_new,
            "rows_duplicate": rows_duplicate,
            "rows_error": rows_error,
            "journal_entries_created": count_journal,
            "legacy_transactions_created": count_simple,
            "normalized_dates": normalized_dates,
            "unparsable_dates": unparsable_dates,
        },
        "duplicate_reasons": dict(sorted(duplicate_reasons.items())),
        "error_reasons": dict(sorted(error_reasons.items())),
    }
    # Keep legacy keys for existing route/tests.
    summary.update(
        {
            "count_simple": count_simple,
            "count_journal": count_journal,
            "normalized_dates": normalized_dates,
            "unparsable_dates": unparsable_dates,
            "skipped_unbalanced": skipped_unbalanced,
            "skipped_existing": skipped_existing,
            "rows_new": rows_new,
            "rows_duplicate": rows_duplicate,
            "rows_error": rows_error,
        }
    )
    return summary


def import_csv_transactions(
    raw_csv: str,
    user_id: int,
    *,
    filename: str | None = None,
    force: bool = False,
    write_mode: str = "journal",
    idempotency_enabled: bool = True,
) -> Dict[str, object]:
    """Parse, normalize, dedupe, post, and summarize CSV import deterministically."""
    mode = _valid_write_mode(write_mode)
    normalized_dates = 0
    unparsable_dates = 0
    count_simple = 0
    count_journal = 0
    rows_new = 0
    rows_duplicate = 0
    rows_error = 0
    duplicate_reasons: Counter = Counter()
    error_reasons: Counter = Counter()
    skipped_unbalanced: list[str] = []
    skipped_existing: list[str] = []

    file_sha = hashlib.sha256(raw_csv.encode("utf-8")).hexdigest()

    existing_batch = CsvImportBatch.query.filter_by(user_id=user_id, file_sha256=file_sha).first()
    if idempotency_enabled and existing_batch and not force:
        duplicate_rows = int(existing_batch.row_count or 0)
        duplicate_reasons[ROW_DUPLICATE_BATCH] += duplicate_rows
        return _build_summary(
            batch_id=existing_batch.id,
            file_sha256=file_sha,
            write_mode=mode,
            rows_total=duplicate_rows,
            rows_new=0,
            rows_duplicate=duplicate_rows,
            rows_error=0,
            count_journal=0,
            count_simple=0,
            normalized_dates=0,
            unparsable_dates=0,
            duplicate_reasons=duplicate_reasons,
            error_reasons=error_reasons,
            skipped_duplicate_batch=True,
            skipped_unbalanced=[],
            skipped_existing=[],
        )

    if existing_batch:
        batch = existing_batch
        batch.filename = (filename or batch.filename or "")[:255] or None
        batch.status = "processing"
        batch.applied_at = None
        batch.row_count = 0
    else:
        batch = CsvImportBatch(
            user_id=user_id,
            file_sha256=file_sha,
            filename=(filename or "")[:255] or None,
            status="processing",
        )
        db.session.add(batch)
        db.session.flush()

    raw_rows: list[dict] = []
    parsed_rows: list[ParsedCsvRow] = []

    lines = raw_csv.splitlines()
    reader = csv.DictReader(lines)
    for idx, row in enumerate(reader, start=1):
        raw_rows.append(row)
        drow = _norm_key_dict(row)
        date_raw = _get_any(drow, ["date", "transaction date", "datetime", "timestamp"])
        date_str, date_parsed, parsed_ok = _parse_date(date_raw)
        if parsed_ok:
            normalized_dates += 1
        elif date_raw:
            unparsable_dates += 1

        description = _normalize_text(_get_any(drow, ["description", "details", "narration", "memo"]))
        memo = _normalize_text(_get_any(drow, ["memo", "note", "notes"]))
        parsed = ParsedCsvRow(
            row_number=idx,
            date_str=date_str,
            date_parsed=date_parsed,
            date_token=_normalize_date_token(date_str, date_parsed),
            description=description,
            description_norm=_normalize_text_lower(description),
            memo=memo,
            memo_norm=_normalize_text_lower(memo),
            currency=_normalize_currency(_get_any(drow, ["currency", "currency_code", "curr"])),
            debit_account=_normalize_text(_get_any(drow, ["debit_account", "debit account", "debitacct", "debit"])),
            credit_account=_normalize_text(_get_any(drow, ["credit_account", "credit account", "creditacct", "credit"])),
            debit_amount=_safe_decimal(_get_any(drow, ["debit_amount", "debit amount", "debit"])),
            credit_amount=_safe_decimal(_get_any(drow, ["credit_amount", "credit amount", "credit"])),
            external_txn_id=_normalize_external_txn_id(_get_any(drow, ["transaction_id", "transaction id", "txn_id"])),
            row_sha256="",
        )
        parsed_rows.append(parsed)

    parsed_rows = [ParsedCsvRow(**{**row.__dict__, "row_sha256": _row_sha256(row)}) for row in parsed_rows]

    try:
        groups: Dict[str, List[ParsedCsvRow]] = {}
        for row in parsed_rows:
            key = row.external_txn_id or f"ROW:{row.row_number}"
            groups.setdefault(key, []).append(row)

        for key, items in groups.items():
            reference = _group_reference(key, items)
            first_item = items[0]

            built_lines: list[CandidateLine] = []
            line_no = 1

            for item in items:
                counterparty_norm = _normalize_text_lower(item.description or item.memo)

                if item.debit_account and item.debit_amount > 0:
                    acc = ensure_account(user_id, item.debit_account)
                    dedupe = _row_dedupe_key(
                        date_token=item.date_token,
                        amount=item.debit_amount,
                        currency=item.currency,
                        counterparty_norm=counterparty_norm,
                        account_id=acc.id,
                        direction="D",
                        external_txn_id=item.external_txn_id,
                    )
                    dup = (
                        CsvImportRow.query.filter_by(
                            user_id=user_id,
                            account_id=acc.id,
                            direction="D",
                            row_dedupe_key=dedupe,
                        ).first()
                        is not None
                    )
                    built_lines.append(
                        CandidateLine(
                            payload=JournalLinePayload(
                                dc="D",
                                account_id=acc.id,
                                amount=item.debit_amount,
                                currency_code=item.currency,
                                memo=item.memo,
                                line_no=line_no,
                            ),
                            row_number=item.row_number,
                            row_sha256=item.row_sha256,
                            row_dedupe_key=dedupe,
                            external_txn_id=item.external_txn_id,
                            account_id=acc.id,
                            direction="D",
                            amount=item.debit_amount,
                            currency=item.currency,
                            effective_date=item.date_parsed,
                            counterparty_norm=counterparty_norm,
                            duplicate=dup,
                        )
                    )
                    line_no += 1

                if item.credit_account and item.credit_amount > 0:
                    acc = ensure_account(user_id, item.credit_account)
                    dedupe = _row_dedupe_key(
                        date_token=item.date_token,
                        amount=item.credit_amount,
                        currency=item.currency,
                        counterparty_norm=counterparty_norm,
                        account_id=acc.id,
                        direction="C",
                        external_txn_id=item.external_txn_id,
                    )
                    dup = (
                        CsvImportRow.query.filter_by(
                            user_id=user_id,
                            account_id=acc.id,
                            direction="C",
                            row_dedupe_key=dedupe,
                        ).first()
                        is not None
                    )
                    built_lines.append(
                        CandidateLine(
                            payload=JournalLinePayload(
                                dc="C",
                                account_id=acc.id,
                                amount=item.credit_amount,
                                currency_code=item.currency,
                                memo=item.memo,
                                line_no=line_no,
                            ),
                            row_number=item.row_number,
                            row_sha256=item.row_sha256,
                            row_dedupe_key=dedupe,
                            external_txn_id=item.external_txn_id,
                            account_id=acc.id,
                            direction="C",
                            amount=item.credit_amount,
                            currency=item.currency,
                            effective_date=item.date_parsed,
                            counterparty_norm=counterparty_norm,
                            duplicate=dup,
                        )
                    )
                    line_no += 1

            if not built_lines:
                rows_error += len(items)
                error_reasons[ROW_ERROR_NO_POSTABLE_LINES] += len(items)
                continue

            duplicate_lines = [ln for ln in built_lines if ln.duplicate]
            if duplicate_lines:
                if len(duplicate_lines) == len(built_lines):
                    rows_duplicate += len(items)
                    duplicate_reasons[ROW_DUPLICATE_KEY] += len(items)
                    continue
                rows_error += len(items)
                error_reasons[ROW_ERROR_PARTIAL_DUPLICATE_GROUP] += len(items)
                skipped_unbalanced.append(str(key))
                continue

            group_rows_new = 0
            group_journal_count = 0
            group_simple_count = 0
            try:
                with db.session.begin_nested():
                    if mode == "legacy":
                        # Legacy mode only supports simple two-line records.
                        if len(built_lines) != 2:
                            rows_error += len(items)
                            error_reasons[ROW_ERROR_LEGACY_UNSUPPORTED_SHAPE] += len(items)
                            continue
                        debit_line = next((ln for ln in built_lines if ln.direction == "D"), None)
                        credit_line = next((ln for ln in built_lines if ln.direction == "C"), None)
                        if not debit_line or not credit_line:
                            rows_error += len(items)
                            error_reasons[ROW_ERROR_LEGACY_UNSUPPORTED_SHAPE] += len(items)
                            continue
                        tx = Transaction(
                            date=first_item.date_str,
                            description=first_item.description,
                            debit_account=ensure_account(user_id, first_item.debit_account or "").name,
                            debit_amount=float(debit_line.amount),
                            credit_account=ensure_account(user_id, first_item.credit_account or "").name,
                            credit_amount=float(credit_line.amount),
                            user_id=user_id,
                            debit_account_id=debit_line.account_id,
                            credit_account_id=credit_line.account_id,
                            date_parsed=first_item.date_parsed,
                        )
                        db.session.add(tx)
                        db.session.flush()
                        for line in built_lines:
                            db.session.add(
                                CsvImportRow(
                                    batch_id=batch.id,
                                    user_id=user_id,
                                    row_number=line.row_number,
                                    row_sha256=line.row_sha256,
                                    row_dedupe_key=line.row_dedupe_key,
                                    external_txn_id=line.external_txn_id,
                                    account_id=line.account_id,
                                    direction=line.direction,
                                    amount=line.amount,
                                    currency=line.currency,
                                    effective_date=line.effective_date,
                                    counterparty_norm=line.counterparty_norm,
                                    status="imported",
                                )
                            )
                        group_simple_count = 1
                        group_rows_new = len(items)
                    else:
                        entry = create_journal_entry(
                            user_id=user_id,
                            date=first_item.date_str,
                            date_parsed=first_item.date_parsed,
                            description=first_item.description or key,
                            reference=reference,
                            lines=[ln.payload for ln in built_lines],
                        )
                        db.session.flush()

                        # Dual mode mirrors simple two-line records into legacy table.
                        if mode == "dual" and len(built_lines) == 2:
                            debit_line = next((ln for ln in built_lines if ln.direction == "D"), None)
                            credit_line = next((ln for ln in built_lines if ln.direction == "C"), None)
                            if debit_line and credit_line:
                                tx = Transaction(
                                    date=first_item.date_str,
                                    description=first_item.description,
                                    debit_account=ensure_account(user_id, first_item.debit_account or "").name,
                                    debit_amount=float(debit_line.amount),
                                    credit_account=ensure_account(user_id, first_item.credit_account or "").name,
                                    credit_amount=float(credit_line.amount),
                                    user_id=user_id,
                                    debit_account_id=debit_line.account_id,
                                    credit_account_id=credit_line.account_id,
                                    date_parsed=first_item.date_parsed,
                                )
                                db.session.add(tx)
                                db.session.flush()
                                db.session.add(
                                    TransactionJournalLink(
                                        user_id=user_id,
                                        transaction_id=tx.id,
                                        journal_entry_id=entry.id,
                                        source="strong_dual_write",
                                    )
                                )
                                group_simple_count = 1

                        for line in built_lines:
                            db.session.add(
                                CsvImportRow(
                                    batch_id=batch.id,
                                    user_id=user_id,
                                    row_number=line.row_number,
                                    row_sha256=line.row_sha256,
                                    row_dedupe_key=line.row_dedupe_key,
                                    external_txn_id=line.external_txn_id,
                                    account_id=line.account_id,
                                    direction=line.direction,
                                    amount=line.amount,
                                    currency=line.currency,
                                    effective_date=line.effective_date,
                                    counterparty_norm=line.counterparty_norm,
                                    status="imported",
                                    journal_entry_id=entry.id,
                                )
                            )
                        group_journal_count = 1
                        group_rows_new = len(items)
            except JournalBalanceError:
                rows_error += len(items)
                error_reasons[ROW_ERROR_UNBALANCED_JOURNAL] += len(items)
                skipped_unbalanced.append(str(key))
                continue
            except Exception as exc:
                mapped = map_journal_db_exception(exc)
                if mapped:
                    error_code, _, _ = mapped
                    rows_error += len(items)
                    if error_code == JOURNAL_ERROR_UNBALANCED:
                        error_reasons[ROW_ERROR_UNBALANCED_JOURNAL] += len(items)
                        skipped_unbalanced.append(str(key))
                    elif error_code == JOURNAL_ERROR_INVALID_DC:
                        error_reasons[ROW_ERROR_INVALID_DC] += len(items)
                    else:
                        error_reasons[ROW_ERROR_UNBALANCED_JOURNAL] += len(items)
                    continue
                raise

            count_journal += group_journal_count
            count_simple += group_simple_count
            rows_new += group_rows_new

        batch.row_count = len(parsed_rows)
        batch.status = "applied"
        batch.applied_at = datetime.datetime.utcnow()
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    # Feed adaptive hints from CSV contents.
    try:
        for row in raw_rows:
            desc = row.get("description", "") or ""
            da = row.get("debit_account", "") or ""
            ca = row.get("credit_account", "") or ""
            if da:
                record_suggestion_hint(user_id, "debit", desc, da)
            if ca:
                record_suggestion_hint(user_id, "credit", desc, ca)
    except Exception:
        pass

    return _build_summary(
        batch_id=batch.id,
        file_sha256=file_sha,
        write_mode=mode,
        rows_total=len(parsed_rows),
        rows_new=rows_new,
        rows_duplicate=rows_duplicate,
        rows_error=rows_error,
        count_journal=count_journal,
        count_simple=count_simple,
        normalized_dates=normalized_dates,
        unparsable_dates=unparsable_dates,
        duplicate_reasons=duplicate_reasons,
        error_reasons=error_reasons,
        skipped_duplicate_batch=False,
        skipped_unbalanced=skipped_unbalanced,
        skipped_existing=skipped_existing,
    )
