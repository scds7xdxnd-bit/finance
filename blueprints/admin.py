import csv
import datetime as _dt
import io
import math
import os
import platform
import sys
import tempfile
from collections import defaultdict

from finance_app.extensions import db
from finance_app.lib.auth import csrf_token_valid, current_user, require_admin
from finance_app.lib.dates import _parse_date_tuple
from finance_app.models.accounting_models import (
    AdminActionAudit,
    AccountSuggestionHint,
    AccountSuggestionLog,
    JournalEntry,
    LoginSession,
    SuggestionFeedback,
    Transaction,
)
from finance_app.models.user_models import User, UserPost, UserProfile
from finance_app.services.account_service import _BG_JOBS, start_background_assign_account_ids
from finance_app.services.schema_guard_service import guard_capabilities, validate_schema_guard_bypass
from finance_app.services.user_model_service import (
    list_user_model_statuses,
    start_background_user_model_training,
    train_user_model,
    user_model_status,
)
from flask import Blueprint, Response, current_app, flash, redirect, render_template, request, url_for
from ml.journal_model import JournalModel  # import the new ML module
from sqlalchemy import func

admin_bp = Blueprint('admin_bp', __name__)


def _csrf_ok() -> bool:
    return csrf_token_valid()


def _now_ms() -> int:
    return int(_dt.datetime.now(_dt.timezone.utc).timestamp() * 1000)


def _cooldown_seconds() -> int:
    try:
        return max(0, int(current_app.config.get("ADMIN_ACTION_COOLDOWN_SECONDS", 5)))
    except Exception:
        return 5


def _confirm_action(action: str) -> tuple[bool, str | None]:
    expected = (action or "").strip()
    provided = (request.form.get("confirm_action") or request.headers.get("X-Confirm-Action") or "").strip()
    if provided != expected:
        return False, "Confirmation mismatch. Please confirm the action again."

    raw = (request.form.get("confirm_at_ms") or request.headers.get("X-Confirm-At-Ms") or "").strip()
    if not raw:
        return False, "Confirmation cooldown is required for this action."
    try:
        at_ms = int(raw)
    except Exception:
        return False, "Invalid confirmation timestamp."
    age_ms = _now_ms() - at_ms
    min_age_ms = _cooldown_seconds() * 1000
    if age_ms < min_age_ms:
        wait_s = _cooldown_seconds()
        return False, f"Please wait {wait_s} seconds before executing this action."
    if age_ms > 10 * 60 * 1000:
        return False, "Confirmation expired. Please confirm again."
    return True, None


def _audit_admin_action(
    *,
    actor_user_id: int,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    status: str = "ok",
    reason: str | None = None,
    details: dict | None = None,
) -> None:
    try:
        db.session.add(
            AdminActionAudit(
                actor_user_id=actor_user_id,
                action=action[:64],
                target_type=(target_type or "")[:64] or None,
                target_id=(target_id or "")[:64] or None,
                status=(status or "ok")[:20],
                reason=(reason or "")[:255] or None,
                details=details or None,
            )
        )
        db.session.commit()
    except Exception:
        db.session.rollback()


@admin_bp.before_request
def _guard_admin_mutations():
    if request.method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    user = current_user()
    if not user or not user.is_admin:
        flash('Admin access required.')
        return redirect(url_for('auth_bp.login'))
    if not _csrf_ok():
        return {"ok": False, "error": "CSRF token missing or invalid."}, 400
    enforce_guard = bool(current_app.config.get("SCHEMA_GUARD_ENFORCE", True))
    bypass_ok, bypass_meta = validate_schema_guard_bypass(current_app.config)
    if not bypass_ok:
        return bypass_meta, 503
    if not enforce_guard:
        current_app.logger.warning(
            "schema_guard_bypass_enabled path=%s method=%s user_id=%s until=%s reason=%s",
            request.path,
            request.method,
            user.id,
            bypass_meta.get("until"),
            bypass_meta.get("reason"),
        )
        _audit_admin_action(
            actor_user_id=user.id,
            action="schema_guard_bypass",
            target_type="endpoint",
            target_id=request.path,
            status="warning",
            reason=str(bypass_meta.get("reason") or "bypass_enabled")[:255],
            details={
                "method": request.method,
                "until": bypass_meta.get("until"),
            },
        )
    ok_guard, payload, _status = guard_capabilities(["admin_audit"], enforce=enforce_guard)
    if not ok_guard:
        return payload, 503
    return None


def _percentile(vals, pct):
    if not vals:
        return None
    vals = sorted(vals)
    k = (len(vals) - 1) * pct
    f = int(math.floor(k))
    c = int(math.ceil(k))
    if f == c:
        return vals[f]
    return vals[f] + (vals[c] - vals[f]) * (k - f)


def _aggregate_log_metrics(uid_int=None, cutoff=None):
    logs_q = db.session.query(AccountSuggestionLog)
    if uid_int:
        logs_q = logs_q.filter(AccountSuggestionLog.user_id == uid_int)
    if cutoff:
        logs_q = logs_q.filter(AccountSuggestionLog.created_at >= cutoff)
    logs = logs_q.with_entities(
        AccountSuggestionLog.model_version,
        AccountSuggestionLog.model_path,
        AccountSuggestionLog.raw_features,
        AccountSuggestionLog.created_at,
    ).all()

    latency_values = []
    fallback_total = 0
    errors_total = 0
    status_counts = defaultdict(int)
    model_versions = defaultdict(int)
    model_hashes = defaultdict(int)
    latest_model_version = None
    latest_model_path = None
    latest_model_hash = None
    latest_seen_at = None
    reward_sum = 0.0
    reward_count = 0
    mrr_sum = 0.0
    mrr_count = 0
    rank_counts = defaultdict(int)
    error_codes = defaultdict(int)

    for mv, mp, rf, created_at in logs:
        features = rf if isinstance(rf, dict) else {}
        latency_val = features.get('latency_ms') or features.get('client_latency_ms')
        try:
            if latency_val is not None:
                latency_values.append(float(latency_val))
        except Exception:
            pass
        status_value = str(features.get('status') or 'ok').lower()
        fallback_flag = bool(features.get('fallback')) or status_value == 'fallback'
        if fallback_flag:
            status_value = 'fallback'
            fallback_total += 1
        err_val = features.get('error') or features.get('error_code')
        if err_val:
            try:
                err_key = str(err_val)[:80]
            except Exception:
                err_key = 'error'
            error_codes[err_key] += 1
            errors_total += 1
        status_counts[status_value] += 1

        version = mv or features.get('model_version')
        path = mp or features.get('model_path')
        mhash = features.get('model_hash') or features.get('model_version_hash')
        if version:
            model_versions[version] += 1
        if mhash:
            model_hashes[mhash] += 1
        if created_at and (latest_seen_at is None or created_at > latest_seen_at):
            latest_seen_at = created_at
            latest_model_version = version
            latest_model_path = path
            latest_model_hash = mhash

        try:
            if features.get('reward') is not None:
                reward_sum += float(features.get('reward') or 0.0)
                reward_count += 1
            if features.get('mrr') is not None:
                mrr_sum += float(features.get('mrr') or 0.0)
                mrr_count += 1
            cr = features.get('chosen_rank')
            if cr in (1, 2, 3):
                rank_counts[int(cr)] += 1
            else:
                rank_counts["manual"] += 1
        except Exception:
            pass

    for key in ("ok", "fallback", "error"):
        status_counts.setdefault(key, 0)
    for key in (1, 2, 3, "manual"):
        rank_counts.setdefault(key, 0)

    coverage_total = len(logs)
    latency_p50 = _percentile(latency_values, 0.5)
    latency_p95 = _percentile(latency_values, 0.95)
    latency_avg = (sum(latency_values) / len(latency_values)) if latency_values else None
    avg_reward = (reward_sum / reward_count) if reward_count else None
    avg_mrr = (mrr_sum / mrr_count) if mrr_count else None
    rank_total = sum(rank_counts.values()) or 0
    denom = coverage_total or rank_total or 0
    top1_hits = rank_counts.get(1, 0)
    top3_hits = rank_counts.get(1, 0) + rank_counts.get(2, 0) + rank_counts.get(3, 0)
    manual_hits = rank_counts.get("manual", 0)
    top1_rate = (top1_hits / denom) if denom else 0.0
    top3_rate = (top3_hits / denom) if denom else 0.0
    manual_rate = (manual_hits / denom) if denom else 0.0
    rank_distribution = {
        "1": (rank_counts.get(1, 0) / denom) if denom else 0.0,
        "2": (rank_counts.get(2, 0) / denom) if denom else 0.0,
        "3": (rank_counts.get(3, 0) / denom) if denom else 0.0,
        "manual": (rank_counts.get("manual", 0) / denom) if denom else 0.0,
    }

    return {
        'coverage_total': coverage_total,
        'errors_total': errors_total,
        'fallback_total': fallback_total,
        'latency_p50': latency_p50,
        'latency_p95': latency_p95,
        'latency_avg': latency_avg,
        'latency_samples': len(latency_values),
        'status_counts': dict(status_counts),
        'avg_reward': avg_reward,
        'avg_mrr': avg_mrr,
        'reward_samples': reward_count,
        'mrr_samples': mrr_count,
        'top1_rate': top1_rate,
        'top3_rate': top3_rate,
        'manual_rate': manual_rate,
        'rank_counts': {k: int(v) for k, v in rank_counts.items()},
        'rank_distribution': rank_distribution,
        'model_versions': dict(model_versions),
        'model_hashes': dict(model_hashes),
        'latest_model_version': latest_model_version,
        'latest_model_path': latest_model_path,
        'latest_model_hash': latest_model_hash,
        'error_codes': dict(error_codes),
    }


def _rank_miss_pairs(uid_int=None, cutoff=None, limit=2000, max_rows=15):
    """Return top pairs where top-1 was not chosen (or manual choice)."""
    q = db.session.query(AccountSuggestionLog)
    if uid_int:
        q = q.filter(AccountSuggestionLog.user_id == uid_int)
    if cutoff:
        q = q.filter(AccountSuggestionLog.created_at >= cutoff)
    q = q.order_by(AccountSuggestionLog.id.desc()).limit(limit)
    pairs = defaultdict(int)
    for log in q.all():
        features = log.raw_features if isinstance(log.raw_features, dict) else {}
        chosen_rank = features.get('chosen_rank')
        if chosen_rank in (1,):
            continue
        chosen = (log.chosen_account or '').strip() or 'manual'
        preds = log.predictions or []
        top_pred = ''
        if preds and isinstance(preds, list):
            try:
                top_pred = (preds[0].get('account_name') or '').strip()
            except Exception:
                top_pred = ''
        key = (top_pred or '—', chosen)
        pairs[key] += 1
    ranked = sorted(pairs.items(), key=lambda kv: kv[1], reverse=True)[:max_rows]
    return [{'predicted': k[0], 'chosen': k[1], 'count': v} for (k, v) in ranked]


@admin_bp.route('/admin', methods=['GET'])
def admin():
    user = current_user()
    if not user or not user.is_admin:
        flash('Admin access required.')
        return redirect(url_for('auth_bp.login'))
    users = User.query.all()
    transactions = Transaction.query.all()
    return render_template('admin.html', user=user, users=users, transactions=transactions)


@admin_bp.route('/admin/grant/<int:user_id>', methods=['POST'])
@require_admin
def grant_admin(user_id):
    user = current_user()
    if not user or not user.is_admin:
        flash('Admin access required.')
        return redirect(url_for('auth_bp.login'))
    ok, err = _confirm_action("grant_admin")
    if not ok:
        flash(err)
        _audit_admin_action(
            actor_user_id=user.id,
            action="grant_admin",
            target_type="user",
            target_id=str(user_id),
            status="blocked",
            reason=err,
        )
        return redirect(url_for('admin_bp.admin_users'))
    target = db.session.get(User, user_id)
    if target and target.username != 'Admin1':
        target.is_admin = True
        db.session.commit()
        _audit_admin_action(
            actor_user_id=user.id,
            action="grant_admin",
            target_type="user",
            target_id=str(target.id),
            status="ok",
        )
        flash(f'Granted admin rights to {target.username}.')
    else:
        _audit_admin_action(
            actor_user_id=user.id,
            action="grant_admin",
            target_type="user",
            target_id=str(user_id),
            status="rejected",
            reason="target_not_found_or_protected",
        )
    return redirect(url_for('admin_bp.admin_users'))


@admin_bp.route('/admin/delete/<int:user_id>', methods=['POST'])
@require_admin
def delete_user(user_id):
    user = current_user()
    if not user or not user.is_admin:
        flash('Admin access required.')
        return redirect(url_for('auth_bp.login'))
    ok, err = _confirm_action("delete_user")
    if not ok:
        flash(err)
        _audit_admin_action(
            actor_user_id=user.id,
            action="delete_user",
            target_type="user",
            target_id=str(user_id),
            status="blocked",
            reason=err,
        )
        return redirect(url_for('admin_bp.admin_users'))
    target = db.session.get(User, user_id)
    if target and target.username != 'Admin1':
        confirm_name = (request.form.get("confirm_username") or "").strip()
        if confirm_name != target.username:
            flash("Please type the exact username to confirm deletion.")
            _audit_admin_action(
                actor_user_id=user.id,
                action="delete_user",
                target_type="user",
                target_id=str(target.id),
                status="blocked",
                reason="confirm_username_mismatch",
            )
            return redirect(url_for('admin_bp.admin_users'))
        # Remove related data: transactions, profile, and posts
        deleted_username = target.username
        Transaction.query.filter_by(user_id=target.id).delete()
        prof = UserProfile.query.filter_by(user_id=target.id).first()
        if prof:
            UserPost.query.filter_by(profile_id=prof.id).delete()
            db.session.delete(prof)
        db.session.delete(target)
        db.session.commit()
        _audit_admin_action(
            actor_user_id=user.id,
            action="delete_user",
            target_type="user",
            target_id=str(user_id),
            status="ok",
            details={"username": deleted_username},
        )
        flash(f'Deleted user {deleted_username} and all related transactions.')
    else:
        _audit_admin_action(
            actor_user_id=user.id,
            action="delete_user",
            target_type="user",
            target_id=str(user_id),
            status="rejected",
            reason="target_not_found_or_protected",
        )
        flash('Cannot delete Admin1 or user not found.')
    return redirect(url_for('admin_bp.admin_users'))


@admin_bp.route('/admin/revoke/<int:user_id>', methods=['POST'])
@require_admin
def revoke_admin(user_id):
    user = current_user()
    if not user or not user.is_admin:
        flash('Admin access required.')
        return redirect(url_for('auth_bp.login'))
    ok, err = _confirm_action("revoke_admin")
    if not ok:
        flash(err)
        _audit_admin_action(
            actor_user_id=user.id,
            action="revoke_admin",
            target_type="user",
            target_id=str(user_id),
            status="blocked",
            reason=err,
        )
        return redirect(url_for('admin_bp.admin_users'))
    target = db.session.get(User, user_id)
    if target and target.username != 'Admin1':
        target.is_admin = False
        db.session.commit()
        _audit_admin_action(
            actor_user_id=user.id,
            action="revoke_admin",
            target_type="user",
            target_id=str(target.id),
            status="ok",
        )
        flash(f'Revoked admin rights from {target.username}.')
    else:
        _audit_admin_action(
            actor_user_id=user.id,
            action="revoke_admin",
            target_type="user",
            target_id=str(user_id),
            status="rejected",
            reason="target_not_found_or_protected",
        )
    return redirect(url_for('admin_bp.admin_users'))


@admin_bp.route('/admin/users', methods=['GET'])
def admin_users():
    user = current_user()
    if not user or not user.is_admin:
        flash('Admin access required.')
        return redirect(url_for('auth_bp.login'))
    users = User.query.all()
    supervisor = next((u for u in users if u.is_admin and (u.username == 'Admin1' or u.id == 1)), None)
    other_users = [u for u in users if not (u.is_admin and (u.username == 'Admin1' or u.id == 1))]
    sorted_users = [supervisor] + other_users if supervisor else users
    user_stats = {}
    for u in sorted_users:
        tx_legacy = Transaction.query.filter_by(user_id=u.id).count()
        tx_journal = JournalEntry.query.filter_by(user_id=u.id).count() if JournalEntry else 0
        tx_count = tx_legacy + tx_journal
        sessions = LoginSession.query.filter_by(user_id=u.id).order_by(LoginSession.login_time.desc()).all()
        session_count = len(sessions)
        latest_login = sessions[0].login_time.strftime('%Y-%m-%d %H:%M:%S') if sessions else 'N/A'
        latest_logout = sessions[0].logout_time.strftime('%Y-%m-%d %H:%M:%S') if sessions and sessions[0].logout_time else 'N/A'
        user_stats[u.id] = {
            'tx_count': tx_count,
            'tx_legacy': tx_legacy,
            'tx_journal': tx_journal,
            'session_count': session_count,
            'latest_login': latest_login,
            'latest_logout': latest_logout
        }
    return render_template('admin_users.html', user=user, users=sorted_users, user_stats=user_stats)


@admin_bp.route('/admin/tools', methods=['GET'])
def admin_tools():
    user = current_user()
    if not user or not user.is_admin:
        flash('Admin access required.')
        return redirect(url_for('auth_bp.login'))
    jobs = _BG_JOBS
    all_users = User.query.order_by(User.username.asc()).all()
    user_map = {u.id: u.username for u in all_users}
    model_statuses = []
    for u in all_users:
        try:
            model_statuses.append(user_model_status(u.id))
        except Exception:
            continue
    return render_template('admin_tools.html', user=user, jobs=jobs, all_users=all_users, model_statuses=model_statuses, user_map=user_map)


@admin_bp.route('/admin/download_login_sessions', methods=['GET'])
def download_login_sessions():
    user = current_user()
    if not user or not user.is_admin:
        flash('Admin access required.')
        return redirect(url_for('auth_bp.login'))

    sessions = LoginSession.query.order_by(LoginSession.login_time.desc()).all()
    user_map = {u.id: u for u in User.query.all()}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['session_id', 'user_id', 'username', 'login_time', 'logout_time', 'duration_seconds'])
    for s in sessions:
        u = user_map.get(s.user_id)
        username = u.username if u else 'Unknown'
        login_ts = s.login_time.isoformat(sep=' ') if s.login_time else ''
        logout_ts = s.logout_time.isoformat(sep=' ') if s.logout_time else ''
        duration = ''
        try:
            if s.logout_time and s.login_time:
                duration = int((s.logout_time - s.login_time).total_seconds())
        except Exception:
            duration = ''
        writer.writerow([s.id, s.user_id, username, login_ts, logout_ts, duration])

    csv_data = output.getvalue()
    output.close()
    return Response(csv_data, mimetype='text/csv', headers={
        'Content-Disposition': 'attachment; filename=login_sessions.csv'
    })


@admin_bp.route('/admin/download_user_list', methods=['GET'])
def download_user_list():
    user = current_user()
    if not user or not user.is_admin:
        flash('Admin access required.')
        return redirect(url_for('auth_bp.login'))

    users = User.query.order_by(User.username.asc()).all()
    sessions = LoginSession.query.order_by(LoginSession.login_time.desc()).all()
    session_map = {}
    for s in sessions:
        info = session_map.setdefault(s.user_id, {'count': 0, 'last_login': None, 'last_logout': None})
        info['count'] += 1
        if s.login_time and (info['last_login'] is None or s.login_time > info['last_login']):
            info['last_login'] = s.login_time
        if s.logout_time and (info['last_logout'] is None or s.logout_time > info['last_logout']):
            info['last_logout'] = s.logout_time

    def fmt_dt(dt):
        return dt.strftime('%Y-%m-%d %H:%M:%S') if dt else ''

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['user_id', 'username', 'email', 'is_admin', 'transactions', 'sessions', 'last_login', 'last_logout'])
    for u in users:
        stats = session_map.get(u.id, {})
        tx_count = Transaction.query.filter_by(user_id=u.id).count()
        writer.writerow([
            u.id,
            u.username,
            u.email or '',
            'yes' if u.is_admin else 'no',
            tx_count,
            stats.get('count', 0),
            fmt_dt(stats.get('last_login')),
            fmt_dt(stats.get('last_logout')),
        ])

    csv_data = output.getvalue()
    output.close()
    return Response(csv_data, mimetype='text/csv', headers={
        'Content-Disposition': 'attachment; filename=user_list.csv'
    })


@admin_bp.route('/admin/suggestions')
def admin_suggestions():
    user = current_user()
    if not user or not user.is_admin:
        flash('Admin access required.')
        return redirect(url_for('auth_bp.login'))
    # Optional user filter
    uid = request.args.get('user_id')
    try:
        uid_int = int(uid) if uid else None
    except Exception:
        uid_int = None

    sf_base = db.session.query(SuggestionFeedback)
    # Optional time window (days)
    days = request.args.get('days')
    window_label = "all time"
    cutoff = None
    if days:
        try:
            days_int = int(days)
            if days_int > 0:
                cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=days_int)
                sf_base = sf_base.filter(SuggestionFeedback.timestamp >= cutoff)
                window_label = f"last {days_int} days"
        except Exception:
            pass
    if uid_int:
        sf_base = sf_base.filter(SuggestionFeedback.user_id == uid_int)
    total = sf_base.count() or 0
    debit_total = sf_base.filter(SuggestionFeedback.kind == 'debit').count() or 0
    credit_total = sf_base.filter(SuggestionFeedback.kind == 'credit').count() or 0
    debit_correct = sf_base.filter(SuggestionFeedback.kind == 'debit', SuggestionFeedback.is_correct == True).count() or 0
    credit_correct = sf_base.filter(SuggestionFeedback.kind == 'credit', SuggestionFeedback.is_correct == True).count() or 0
    # Top mismatches
    te_q = db.session.query(SuggestionFeedback.suggested, SuggestionFeedback.actual, func.count(SuggestionFeedback.id).label('cnt'))
    if uid_int:
        te_q = te_q.filter(SuggestionFeedback.user_id == uid_int)
    top_errors = (
        te_q.filter(SuggestionFeedback.is_correct == False)
        .group_by(SuggestionFeedback.suggested, SuggestionFeedback.actual)
        .order_by(func.count(SuggestionFeedback.id).desc())
        .limit(15)
        .all()
    )
    log_metrics = _aggregate_log_metrics(uid_int=uid_int, cutoff=cutoff)
    rank_misses = _rank_miss_pairs(uid_int=uid_int, cutoff=cutoff)
    # Hint corpus stats (learned from manual + CSV)
    ah_base = db.session.query(AccountSuggestionHint)
    if uid_int:
        ah_base = ah_base.filter(AccountSuggestionHint.user_id == uid_int)
    total_hints = db.session.query(func.coalesce(func.sum(AccountSuggestionHint.count), 0))
    if uid_int:
        total_hints = total_hints.filter(AccountSuggestionHint.user_id == uid_int)
    total_hints = total_hints.scalar() or 0
    debit_hints = db.session.query(func.coalesce(func.sum(AccountSuggestionHint.count), 0)).filter(AccountSuggestionHint.kind == 'debit')
    if uid_int:
        debit_hints = debit_hints.filter(AccountSuggestionHint.user_id == uid_int)
    debit_hints = debit_hints.scalar() or 0
    credit_hints = db.session.query(func.coalesce(func.sum(AccountSuggestionHint.count), 0)).filter(AccountSuggestionHint.kind == 'credit')
    if uid_int:
        credit_hints = credit_hints.filter(AccountSuggestionHint.user_id == uid_int)
    credit_hints = credit_hints.scalar() or 0
    distinct_tokens_q = db.session.query(func.count(func.distinct(AccountSuggestionHint.token)))
    if uid_int:
        distinct_tokens_q = distinct_tokens_q.filter(AccountSuggestionHint.user_id == uid_int)
    distinct_tokens = distinct_tokens_q.scalar() or 0
    distinct_pairs_q = db.session.query(AccountSuggestionHint.token, AccountSuggestionHint.account_name).distinct()
    if uid_int:
        distinct_pairs_q = distinct_pairs_q.filter(AccountSuggestionHint.user_id == uid_int)
    distinct_pairs = distinct_pairs_q.count()
    top_tokens_q = db.session.query(AccountSuggestionHint.token, func.sum(AccountSuggestionHint.count).label('tot'))
    if uid_int:
        top_tokens_q = top_tokens_q.filter(AccountSuggestionHint.user_id == uid_int)
    top_tokens = (
        top_tokens_q.group_by(AccountSuggestionHint.token)
        .order_by(func.sum(AccountSuggestionHint.count).desc())
        .limit(15)
        .all()
    )
    stats = {
        'feedback_total': total,
        'debit_total': debit_total,
        'credit_total': credit_total,
        'debit_correct': debit_correct,
        'credit_correct': credit_correct,
        'debit_acc': (round((debit_correct / debit_total) * 100, 1) if debit_total else 0.0),
        'credit_acc': (round((credit_correct / credit_total) * 100, 1) if credit_total else 0.0),
        'total_hints': int(total_hints),
        'debit_hints': int(debit_hints),
        'credit_hints': int(credit_hints),
        'distinct_tokens': int(distinct_tokens),
        'distinct_pairs': int(distinct_pairs),
        'window': window_label,
    }
    stats.update(log_metrics)
    all_users = User.query.order_by(User.username.asc()).all()
    selected_user = db.session.get(User, uid_int) if uid_int else None
    # Add ML model stats
    jm = JournalModel()
    model_stats = {
        'feedback_counts': jm.feedback_counts,
        'cooccurrence_pairs': len(jm.account_cooccurrence) if hasattr(jm, 'account_cooccurrence') else 0,
        'has_embeddings': bool(getattr(jm, 'account_embeddings', None)),
        'latest_model_version': stats.get('latest_model_version'),
        'latest_model_path': stats.get('latest_model_path'),
        'latest_model_hash': stats.get('latest_model_hash'),
        'model_versions': stats.get('model_versions') or {},
        'model_hashes': stats.get('model_hashes') or {},
    }
    return render_template('admin_suggestions.html', user=user, stats=stats, top_errors=top_errors, top_tokens=top_tokens, rank_misses=rank_misses, all_users=all_users, selected_user=selected_user, selected_user_id=uid_int, model_stats=model_stats)


@admin_bp.route('/admin/diagnostics/weasy', methods=['GET'])
def admin_weasy_diagnostics():
    user = current_user()
    if not user or not user.is_admin:
        flash('Admin access required.')
        return redirect(url_for('auth_bp.login'))

    diag = {
        'python_executable': sys.executable,
        'python_version': sys.version,
        'platform': platform.platform(),
        'venv': os.environ.get('VIRTUAL_ENV') or '',
        'import_ok': False,
        'weasy_version': '',
        'render_ok': False,
        'render_error': '',
        'hints': []
    }
    try:
        import weasyprint  # type: ignore
        diag['import_ok'] = True
        diag['weasy_version'] = getattr(weasyprint, '__version__', 'unknown')
        from weasyprint import HTML
        try:
            # minimal in-memory render
            with tempfile.TemporaryDirectory() as td:
                out = os.path.join(td, 'probe.pdf')
                HTML(string='<h1>Probe OK</h1>').write_pdf(out)
                diag['render_ok'] = os.path.exists(out) and os.path.getsize(out) > 0
        except Exception as e:
            diag['render_error'] = f'{e.__class__.__name__}: {e}'
    except Exception as e:
        diag['render_error'] = f'ImportError: {e}'

    # Heuristic hints
    err = diag['render_error'] or ''
    if not diag['import_ok']:
        diag['hints'].append("WeasyPrint isn't importable in this interpreter. Ensure you installed it in the same environment that runs Flask: pip install weasyprint")
    if 'cairo' in err.lower() or 'pangocairo' in err.lower() or 'pango' in err.lower():
        diag['hints'].append('Missing native libs. On macOS (Apple Silicon): brew install pango cairo gdk-pixbuf libffi libxml2 libxslt harfbuzz fribidi librsvg')
    if 'gobject' in err.lower() or 'gi.' in err.lower():
        diag['hints'].append('Ensure pygobject and related libs are present. Some environments require brew install pygobject3 gtk+3')
    diag['hints'].append('Confirm Python path matches: which python3; and sys.executable shown below')

    # Always respond with JSON since the standalone diagnostics page was removed.
    return {
        'ok': bool(diag['import_ok'] and diag['render_ok']),
        'diag': diag,
    }


@admin_bp.route('/admin/suggestions/train', methods=['POST'])
@require_admin
def admin_train_suggestions():
    user = current_user()
    if not user or not user.is_admin:
        flash('Admin access required.')
        return redirect(url_for('auth_bp.login'))
    ok, err = _confirm_action("train_suggestions")
    if not ok:
        flash(err)
        _audit_admin_action(
            actor_user_id=user.id,
            action="train_suggestions",
            status="blocked",
            reason=err,
        )
        return redirect(url_for('admin_bp.admin_suggestions'))
    jm = JournalModel()
    res = jm.train_incremental_mf()
    if res.get('ok'):
        _audit_admin_action(
            actor_user_id=user.id,
            action="train_suggestions",
            status="ok",
            details={"trained_on": int(res.get("trained_on") or 0)},
        )
        flash(f"Model trained on {res.get('trained_on', 0)} accounts.")
    else:
        _audit_admin_action(
            actor_user_id=user.id,
            action="train_suggestions",
            status="failed",
            reason=str(res.get("error") or "training_failed"),
        )
        flash(f"Training failed: {res.get('error')}")
    return redirect(url_for('admin_bp.admin_suggestions'))


@admin_bp.route('/admin/jobs/assign-account-ids', methods=['POST'])
@require_admin
def start_assign_account_ids_job():
    user = current_user()
    if not user or not user.is_admin:
        flash('Admin access required.')
        return redirect(url_for('auth_bp.login'))
    ok, err = _confirm_action("assign_account_ids_job")
    if not ok:
        flash(err)
        _audit_admin_action(
            actor_user_id=user.id,
            action="assign_account_ids_job",
            status="blocked",
            reason=err,
        )
        return redirect(url_for('admin_bp.admin_tools'))
    user_id = request.form.get('user_id')
    try:
        uid = int(user_id) if user_id else None
    except Exception:
        uid = None
    job_id = start_background_assign_account_ids(uid)
    _audit_admin_action(
        actor_user_id=user.id,
        action="assign_account_ids_job",
        target_type="user",
        target_id=(str(uid) if uid is not None else "all"),
        status="ok",
        details={"job_id": job_id},
    )
    flash(f'Started background job {job_id} to assign account ids')
    # Stay on the Jobs page so the admin can monitor progress
    return redirect(url_for('admin_bp.admin_tools'))


@admin_bp.route('/admin/jobs/status', methods=['GET'])
def admin_jobs_status():
    user = current_user()
    if not user or not user.is_admin:
        return { 'ok': False }, 403
    job_id = request.args.get('job_id')
    if job_id:
        data = _BG_JOBS.get(job_id) or {}
        return { 'ok': True, 'job_id': job_id, 'data': data }
    return { 'ok': True, 'jobs': _BG_JOBS }


@admin_bp.route('/admin/user-models/train', methods=['POST'])
@require_admin
def admin_train_user_model():
    user = current_user()
    if not user or not user.is_admin:
        flash('Admin access required.')
        return redirect(url_for('auth_bp.login'))
    ok, err = _confirm_action("train_user_model")
    if not ok:
        flash(err)
        _audit_admin_action(
            actor_user_id=user.id,
            action="train_user_model",
            status="blocked",
            reason=err,
        )
        return redirect(url_for('admin_bp.admin_tools'))
    uid_raw = request.form.get('user_id')
    try:
        uid = int(uid_raw)
    except Exception:
        uid = None
    if not uid:
        _audit_admin_action(
            actor_user_id=user.id,
            action="train_user_model",
            target_type="user",
            target_id=str(uid_raw or ""),
            status="rejected",
            reason="missing_user_id",
        )
        flash('User id is required to train a user model.')
        return redirect(url_for('admin_bp.admin_tools'))
    train_failed = False
    try:
        payload = train_user_model(uid)
    except Exception as exc:
        train_failed = True
        payload = {}
        _audit_admin_action(
            actor_user_id=user.id,
            action="train_user_model",
            target_type="user",
            target_id=str(uid),
            status="failed",
            reason=str(exc),
        )
        flash(f"Training failed: {exc}")
    if payload:
        _audit_admin_action(
            actor_user_id=user.id,
            action="train_user_model",
            target_type="user",
            target_id=str(uid),
            status="ok",
            details={"row_count": int(payload.get("row_count") or 0)},
        )
        flash(f"Trained user model for user {uid} with {payload.get('row_count', 0)} rows.")
    elif not payload and not train_failed:
        _audit_admin_action(
            actor_user_id=user.id,
            action="train_user_model",
            target_type="user",
            target_id=str(uid),
            status="rejected",
            reason="insufficient_rows",
        )
        flash(f"Not enough rows to train a model for user {uid}.")
    return redirect(url_for('admin_bp.admin_tools'))


@admin_bp.route('/admin/jobs/train-user-models', methods=['POST'])
@require_admin
def start_train_user_models_job():
    user = current_user()
    if not user or not user.is_admin:
        flash('Admin access required.')
        return redirect(url_for('auth_bp.login'))
    ok, err = _confirm_action("train_user_models_job")
    if not ok:
        flash(err)
        _audit_admin_action(
            actor_user_id=user.id,
            action="train_user_models_job",
            status="blocked",
            reason=err,
        )
        return redirect(url_for('admin_bp.admin_tools'))
    uid_raw = request.form.get('user_id')
    try:
        uid = int(uid_raw) if uid_raw else None
    except Exception:
        uid = None
    job_id = start_background_user_model_training(uid)
    _audit_admin_action(
        actor_user_id=user.id,
        action="train_user_models_job",
        target_type="user",
        target_id=(str(uid) if uid is not None else "all"),
        status="ok",
        details={"job_id": job_id},
    )
    flash(f'Started user-model training job {job_id}')
    return redirect(url_for('admin_bp.admin_tools'))


def _compute_suggestion_metrics(uid_int=None, cutoff=None):
    # Feedback totals
    base = db.session.query(SuggestionFeedback)
    if uid_int:
        base = base.filter(SuggestionFeedback.user_id == uid_int)
    if cutoff:
        base = base.filter(SuggestionFeedback.timestamp >= cutoff)
    total = base.count() or 0
    debit_total = base.filter(SuggestionFeedback.kind == 'debit').count() or 0
    credit_total = base.filter(SuggestionFeedback.kind == 'credit').count() or 0
    debit_correct = base.filter(SuggestionFeedback.kind == 'debit', SuggestionFeedback.is_correct == True).count() or 0
    credit_correct = base.filter(SuggestionFeedback.kind == 'credit', SuggestionFeedback.is_correct == True).count() or 0
    # Top mismatches
    te_q = db.session.query(SuggestionFeedback.suggested, SuggestionFeedback.actual, func.count(SuggestionFeedback.id).label('cnt'))
    if uid_int:
        te_q = te_q.filter(SuggestionFeedback.user_id == uid_int)
    top_errors = (
        te_q.filter(SuggestionFeedback.is_correct == False)
        .group_by(SuggestionFeedback.suggested, SuggestionFeedback.actual)
        .order_by(func.count(SuggestionFeedback.id).desc())
        .limit(15)
        .all()
    )
    # Hint corpus stats
    ah_base = db.session.query(AccountSuggestionHint)
    if uid_int:
        ah_base = ah_base.filter(AccountSuggestionHint.user_id == uid_int)
    total_hints_q = db.session.query(func.coalesce(func.sum(AccountSuggestionHint.count), 0))
    if uid_int:
        total_hints_q = total_hints_q.filter(AccountSuggestionHint.user_id == uid_int)
    total_hints = total_hints_q.scalar() or 0
    debit_hints_q = db.session.query(func.coalesce(func.sum(AccountSuggestionHint.count), 0)).filter(AccountSuggestionHint.kind == 'debit')
    if uid_int:
        debit_hints_q = debit_hints_q.filter(AccountSuggestionHint.user_id == uid_int)
    debit_hints = debit_hints_q.scalar() or 0
    credit_hints_q = db.session.query(func.coalesce(func.sum(AccountSuggestionHint.count), 0)).filter(AccountSuggestionHint.kind == 'credit')
    if uid_int:
        credit_hints_q = credit_hints_q.filter(AccountSuggestionHint.user_id == uid_int)
    credit_hints = credit_hints_q.scalar() or 0
    distinct_tokens_q = db.session.query(func.count(func.distinct(AccountSuggestionHint.token)))
    if uid_int:
        distinct_tokens_q = distinct_tokens_q.filter(AccountSuggestionHint.user_id == uid_int)
    distinct_tokens = distinct_tokens_q.scalar() or 0
    distinct_pairs_q = db.session.query(AccountSuggestionHint.token, AccountSuggestionHint.account_name).distinct()
    if uid_int:
        distinct_pairs_q = distinct_pairs_q.filter(AccountSuggestionHint.user_id == uid_int)
    distinct_pairs = distinct_pairs_q.count()
    top_tokens_q = db.session.query(AccountSuggestionHint.token, func.sum(AccountSuggestionHint.count).label('tot'))
    if uid_int:
        top_tokens_q = top_tokens_q.filter(AccountSuggestionHint.user_id == uid_int)
    top_tokens = (
        top_tokens_q.group_by(AccountSuggestionHint.token)
        .order_by(func.sum(AccountSuggestionHint.count).desc())
        .limit(15)
        .all()
    )
    stats = {
        'feedback_total': int(total),
        'debit_total': int(debit_total),
        'credit_total': int(credit_total),
        'debit_correct': int(debit_correct),
        'credit_correct': int(credit_correct),
        'debit_incorrect': int((debit_total or 0) - (debit_correct or 0)),
        'credit_incorrect': int((credit_total or 0) - (credit_correct or 0)),
        'debit_acc': float(round((debit_correct / debit_total) * 100, 1) if debit_total else 0.0),
        'credit_acc': float(round((credit_correct / credit_total) * 100, 1) if credit_total else 0.0),
        'total_hints': int(total_hints),
        'debit_hints': int(debit_hints),
        'credit_hints': int(credit_hints),
        'distinct_tokens': int(distinct_tokens),
        'distinct_pairs': int(distinct_pairs),
    }
    stats.update(_aggregate_log_metrics(uid_int=uid_int, cutoff=cutoff))
    return stats, top_errors, top_tokens


@admin_bp.route('/admin/api/suggestions/metrics', methods=['GET'])
def admin_api_suggestions_metrics():
    user = current_user()
    if not user or not user.is_admin:
        return {'ok': False, 'error': 'forbidden'}, 403
    user_id = request.args.get('user_id')
    uid = None
    try:
        uid = int(user_id) if user_id else None
    except Exception:
        uid = None
    days = request.args.get('days')
    cutoff = None
    if days:
        try:
            days_int = int(days)
            if days_int > 0:
                cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=days_int)
        except Exception:
            cutoff = None
    stats, top_errors, top_tokens = _compute_suggestion_metrics(uid, cutoff)
    stats_payload = dict(stats)
    stats_payload['rank_counts'] = {str(k): v for k, v in (stats.get('rank_counts') or {}).items()}
    top_errors_json = [{'suggested': s or None, 'actual': a or None, 'count': int(c)} for (s,a,c) in top_errors]
    top_tokens_json = [{'token': t, 'count': int(tot)} for (t, tot) in top_tokens]
    return { 'ok': True, 'stats': stats_payload, 'top_errors': top_errors_json, 'top_tokens': top_tokens_json }


@admin_bp.route('/admin/api/user-models/status', methods=['GET'])
def admin_api_user_models_status():
    user = current_user()
    if not user or not user.is_admin:
        return {'ok': False, 'error': 'forbidden'}, 403
    uid_raw = request.args.get('user_id')
    try:
        uid = int(uid_raw) if uid_raw else None
    except Exception:
        uid = None
    all_users = User.query.order_by(User.id.asc()).all()
    user_map = {u.id: u.username for u in all_users}
    statuses = list_user_model_statuses([uid] if uid else None)
    for st in statuses:
        st["username"] = user_map.get(st["user_id"], f"user-{st['user_id']}")
    return {'ok': True, 'statuses': statuses}


@admin_bp.route('/admin/api/tx/summary', methods=['GET'])
def admin_api_tx_summary():
    user = current_user()
    if not user or not user.is_admin:
        return {'ok': False, 'error': 'forbidden'}, 403
    # Params
    group = (request.args.get('group') or 'month').lower()  # 'day' or 'month'
    months = int(request.args.get('months') or 12)
    end = _dt.date.today()
    start = end.replace(day=1)
    # Compute start by months back
    y, m = start.year, start.month
    m -= (months - 1)
    while m <= 0:
        m += 12
        y -= 1
    start = _dt.date(y, m, 1)
    q = Transaction.query
    if request.args.get('user_id'):
        try:
            q = q.filter(Transaction.user_id == int(request.args.get('user_id')))
        except Exception:
            pass
    if hasattr(Transaction, 'date_parsed'):
        q = q.filter(Transaction.date_parsed >= start)
    # Fetch and group in Python for portability
    rows = q.all()
    from collections import defaultdict
    agg = defaultdict(lambda: {'debit': 0.0, 'credit': 0.0})
    for t in rows:
        # choose bucket key
        if getattr(t, 'date_parsed', None):
            d = t.date_parsed
        else:
            try:
                y, m, d_ = _parse_date_tuple(t.date)
                d = _dt.date(y, m, d_) if y and m and d_ else None
            except Exception:
                d = None
        if not d:
            continue
        if group == 'day':
            key = d.strftime('%Y-%m-%d')
        else:
            key = d.strftime('%Y-%m')
        agg[key]['debit'] += float(getattr(t, 'debit_amount', 0.0) or 0.0)
        agg[key]['credit'] += float(getattr(t, 'credit_amount', 0.0) or 0.0)
    # Sort by key (date)
    keys = sorted(agg.keys())
    out = []
    for k in keys:
        deb = round(agg[k]['debit'], 2)
        cred = round(agg[k]['credit'], 2)
        out.append({'period': k, 'debit_total': deb, 'credit_total': cred, 'net': round(cred - deb, 2)})
    return {'ok': True, 'group': group, 'series': out}
