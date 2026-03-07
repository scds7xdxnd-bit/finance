"""Accounting, journal, receivable, and loan related models."""
import datetime
import uuid
from decimal import Decimal  # noqa: F401  # kept for potential defaults/extensions

from finance_app.extensions import db


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20))
    description = db.Column(db.String(200))
    debit_account = db.Column(db.String(100))
    debit_amount = db.Column(db.Float)
    credit_account = db.Column(db.String(100))
    credit_amount = db.Column(db.Float)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    debit_account_id = db.Column(db.Integer, db.ForeignKey("account.id"))
    credit_account_id = db.Column(db.Integer, db.ForeignKey("account.id"))
    date_parsed = db.Column(db.Date)

    __table_args__ = (
        db.Index("ix_transaction_user_date_parsed", "user_id", "date_parsed"),
        db.Index("ix_transaction_user_debit_account_id", "user_id", "debit_account_id"),
        db.Index("ix_transaction_user_credit_account_id", "user_id", "credit_account_id"),
    )


class AccountSuggestionHint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    kind = db.Column(db.String(10), nullable=False)  # 'debit' or 'credit'
    token = db.Column(db.String(100), nullable=False)
    account_name = db.Column(db.String(120), nullable=False)
    count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)


class SuggestionFeedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    kind = db.Column(db.String(10), nullable=False)
    description = db.Column(db.Text)
    suggested = db.Column(db.String(120))
    actual = db.Column(db.String(120))
    is_correct = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)


class AccountSuggestionLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    currency = db.Column(db.String(10))
    transaction_id = db.Column(db.String(64), index=True)
    line_id = db.Column(db.String(64))
    line_type = db.Column(db.String(10))
    chosen_account = db.Column(db.String(120))
    model_version = db.Column(db.String(64))
    model_path = db.Column(db.String(255))
    probability = db.Column(db.Float)
    raw_features = db.Column(db.JSON)
    predictions = db.Column(db.JSON)
    description = db.Column(db.Text)
    entry_date = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    responded_at = db.Column(db.DateTime)


class AccountCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    side = db.Column(db.String(10), nullable=False, default="both")  # kept for legacy; unused in UI
    order = db.Column(db.Integer, default=0)
    tb_group = db.Column(db.String(20))
    accounts = db.relationship("Account", backref="category", lazy=True)

    __table_args__ = (
        db.Index("ix_account_category_user_tb_group", "user_id", "tb_group"),
    )


class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    code = db.Column(db.String(20))
    name = db.Column(db.String(100), nullable=False)
    side = db.Column(db.String(10), nullable=False, default="both")  # kept for legacy; unused in UI
    category_id = db.Column(db.Integer, db.ForeignKey("account_category.id"))
    order = db.Column(db.Integer, default=0)
    active = db.Column(db.Boolean, default=True)
    currency_code = db.Column(db.String(10), default="KRW")

    __table_args__ = (
        db.Index("ix_account_user_category_active", "user_id", "category_id", "active"),
    )


class AccountOpeningBalance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    amount = db.Column(db.Float, default=0.0)
    as_of_date = db.Column(db.Date)

    __table_args__ = (
        db.Index("ix_account_opening_balance_user_account", "user_id", "account_id"),
    )


class LoginSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    login_time = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    logout_time = db.Column(db.DateTime)


class TrialBalanceSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True)
    # First TB month (first day of the month). Controls I/E reset behavior.
    first_month = db.Column(db.Date)
    # Date when the user finalized their opening balances (controls calculation cutoff)
    initialized_on = db.Column(db.Date)


class AccountMonthlyBalance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    opening_bd = db.Column(db.Float, default=0.0)
    period_debit = db.Column(db.Float, default=0.0)
    period_credit = db.Column(db.Float, default=0.0)
    closing_balance = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    __table_args__ = (db.UniqueConstraint("user_id", "account_id", "year", "month", name="uq_user_acc_ym"),)


class ReceivableTracker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    journal_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"), nullable=False, index=True)
    journal_line_id = db.Column(db.Integer, db.ForeignKey("journal_line.id"), nullable=False, unique=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False, index=True)
    category = db.Column(db.String(20), nullable=False)  # 'receivable' or 'debt'
    contact_name = db.Column(db.String(120))
    transaction_value = db.Column(db.Numeric(18, 2))
    currency_code = db.Column(db.String(10))
    due_date = db.Column(db.Date)
    amount_paid = db.Column(db.Numeric(18, 2))
    payment_dates = db.Column(db.Text)  # JSON-encoded array of ISO date strings
    remaining_amount = db.Column(db.Numeric(18, 2))
    status = db.Column(db.String(20), default="UNPAID")
    notes = db.Column(db.Text)
    linked_line_id = db.Column(db.Integer, db.ForeignKey("journal_line.id"))
    link_kind = db.Column(db.String(20))
    ignored = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class ReceivableManualEntry(db.Model):
    __tablename__ = "receivable_manual_entry"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False, index=True)
    category = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    currency_code = db.Column(db.String(10), nullable=False, default="KRW")
    description = db.Column(db.String(255))
    reference = db.Column(db.String(120))
    memo = db.Column(db.Text)
    contact_name = db.Column(db.String(120))
    transaction_value = db.Column(db.Numeric(18, 2))
    due_date = db.Column(db.Date)
    payment_dates = db.Column(db.Text)
    notes = db.Column(db.Text)
    date = db.Column(db.String(20))
    date_parsed = db.Column(db.Date)
    status = db.Column(db.String(20), default="UNPAID")
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class LoanGroup(db.Model):
    __tablename__ = "loan_group"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    direction = db.Column(db.String(20), nullable=False)  # receivable or payable
    counterparty = db.Column(db.String(160))
    currency = db.Column(db.String(10), nullable=False, default="KRW")
    principal_amount = db.Column(db.Numeric(18, 2), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="open")
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    links = db.relationship("LoanGroupLink", backref="loan_group", lazy=True, cascade="all, delete-orphan")


class LoanGroupLink(db.Model):
    __tablename__ = "loan_group_link"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    loan_group_id = db.Column(db.String(36), db.ForeignKey("loan_group.id"), nullable=False, index=True)
    journal_line_id = db.Column(db.Integer, db.ForeignKey("journal_line.id"), nullable=False, index=True)
    linked_amount = db.Column(db.Numeric(18, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)

    journal_line = db.relationship("JournalLine", lazy="joined")

    __table_args__ = (db.UniqueConstraint("loan_group_id", "journal_line_id", name="uq_group_line"),)


class JournalEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    # Keep date as string for consistency with Transaction and flexible parsing, plus parsed date for sorting
    date = db.Column(db.String(20))
    date_parsed = db.Column(db.Date)
    description = db.Column(db.String(255))
    reference = db.Column(db.String(120), index=True)  # e.g., 'TX:123' for migrated rows, invoice no, etc.
    posted_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    lines = db.relationship("JournalLine", backref="journal", lazy=True, cascade="all, delete-orphan")

    __table_args__ = (
        db.Index("ix_journal_entry_user_date_parsed", "user_id", "date_parsed"),
        db.Index("ix_journal_entry_user_reference", "user_id", "reference"),
    )


class JournalLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    journal_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"), nullable=False, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False, index=True)
    # 'D' for debit, 'C' for credit
    dc = db.Column(db.String(1), nullable=False)
    # Amounts: prefer fixed precision. SQLite stores NUMERIC; SQLAlchemy coerces to Decimal when bound.
    amount_base = db.Column(db.Numeric(18, 2), nullable=False)
    currency_code = db.Column(db.String(10))  # optional, e.g., 'USD', 'EUR', 'MYR'
    amount_tx = db.Column(db.Numeric(18, 2))  # original currency amount (if different from base)
    fx_rate_to_base = db.Column(db.Numeric(18, 8))  # rate used for conversion (amount_tx * rate = amount_base)
    memo = db.Column(db.Text)
    line_no = db.Column(db.Integer, default=0)

    __table_args__ = (
        db.Index("ix_journal_line_journal_account_dc", "journal_id", "account_id", "dc"),
        db.Index("ix_journal_line_account_dc_journal", "account_id", "dc", "journal_id"),
    )


class TransactionJournalLink(db.Model):
    __tablename__ = "transaction_journal_link"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("transaction.id"), nullable=False)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"), nullable=False)
    source = db.Column(db.String(32), nullable=False, default="manual")
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        db.UniqueConstraint("user_id", "transaction_id", name="uq_tx_journal_link_user_tx"),
        db.UniqueConstraint("user_id", "journal_entry_id", name="uq_tx_journal_link_user_journal_entry"),
        db.CheckConstraint("source IS NOT NULL AND length(trim(source)) > 0", name="ck_tx_journal_link_source_nonempty"),
        db.Index("ix_tx_journal_link_user_journal", "user_id", "journal_entry_id"),
        db.Index("ix_tx_journal_link_user_source", "user_id", "source"),
    )


class TransactionLinkCandidate(db.Model):
    __tablename__ = "transaction_link_candidate"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("transaction.id"), nullable=False, index=True)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"), index=True)
    confidence = db.Column(db.String(20), nullable=False, default="weak")
    reason = db.Column(db.String(120))
    score = db.Column(db.Float)
    status = db.Column(db.String(20), nullable=False, default="pending_review")
    source = db.Column(db.String(40), nullable=False, default="backfill")
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    resolved_at = db.Column(db.DateTime)
    resolved_by = db.Column(db.Integer, db.ForeignKey("user.id"))

    __table_args__ = (
        db.Index("ix_tx_link_candidate_user_status", "user_id", "status"),
        db.Index("ix_tx_link_candidate_user_tx_reason", "user_id", "transaction_id", "reason"),
        db.CheckConstraint("source IS NOT NULL AND length(trim(source)) > 0", name="ck_tx_link_candidate_source_nonempty"),
    )


class CsvImportBatch(db.Model):
    __tablename__ = "csv_import_batch"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    file_sha256 = db.Column(db.String(64), nullable=False)
    filename = db.Column(db.String(255))
    row_count = db.Column(db.Integer, default=0, nullable=False)
    status = db.Column(db.String(20), default="processing", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    applied_at = db.Column(db.DateTime)

    __table_args__ = (
        db.UniqueConstraint("user_id", "file_sha256", name="uq_csv_import_batch_user_file"),
        db.CheckConstraint("status IN ('processing', 'applied', 'failed')", name="ck_csv_import_batch_status"),
    )


class CsvImportRow(db.Model):
    __tablename__ = "csv_import_row"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    batch_id = db.Column(db.String(36), db.ForeignKey("csv_import_batch.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    row_number = db.Column(db.Integer, nullable=False)
    row_sha256 = db.Column(db.String(64), nullable=False)
    row_dedupe_key = db.Column(db.String(64), nullable=False)
    external_txn_id = db.Column(db.String(120))
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False, index=True)
    direction = db.Column(db.String(1), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    currency = db.Column(db.String(10))
    effective_date = db.Column(db.Date)
    counterparty_norm = db.Column(db.String(255))
    status = db.Column(db.String(20), nullable=False, default="imported")
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"), index=True)
    error_code = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "account_id",
            "direction",
            "row_dedupe_key",
            name="uq_csv_import_row_user_account_direction_key",
        ),
        db.CheckConstraint("direction IN ('D', 'C')", name="ck_csv_import_row_direction"),
        db.Index("ix_csv_import_row_user_status", "user_id", "status"),
    )


class TBResetSnapshot(db.Model):
    __tablename__ = "tb_reset_snapshot"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    db_copy_path = db.Column(db.String(512), nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    file_size_bytes = db.Column(db.Integer, nullable=False, default=0)
    reason = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    created_by_admin_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    restore_status = db.Column(db.String(20), default="created", nullable=False)
    restored_at = db.Column(db.DateTime)

    __table_args__ = (
        db.UniqueConstraint("user_id", "db_copy_path", name="uq_tb_reset_snapshot_user_path"),
        db.CheckConstraint("length(sha256) = 64", name="ck_tb_reset_snapshot_sha256_len"),
        db.CheckConstraint("file_size_bytes >= 0", name="ck_tb_reset_snapshot_file_size_nonneg"),
        db.CheckConstraint(
            "restore_status IN ('created', 'restored', 'failed')",
            name="ck_tb_reset_snapshot_restore_status",
        ),
        db.Index("ix_tb_reset_snapshot_user_created", "user_id", "created_at"),
    )


class AdminActionAudit(db.Model):
    __tablename__ = "admin_action_audit"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    action = db.Column(db.String(64), nullable=False)
    target_type = db.Column(db.String(64))
    target_id = db.Column(db.String(64))
    status = db.Column(db.String(20), nullable=False, default="ok")
    reason = db.Column(db.String(255))
    details = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)

    __table_args__ = (
        db.Index("ix_admin_action_audit_actor_created", "actor_user_id", "created_at"),
    )
