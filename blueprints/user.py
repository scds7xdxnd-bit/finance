import datetime
import os
from typing import TYPE_CHECKING

from finance_app.extensions import db
from finance_app.lib.auth import current_user
from finance_app.models.accounting_models import (
    JournalEntry,
    LoginSession,
    SuggestionFeedback,
    Transaction,
)
from finance_app.models.user_models import User, UserPost, UserProfile
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask import session as flask_session
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

if TYPE_CHECKING:  # pragma: no cover - import for type hints only
    pass  # type: ignore

user_bp = Blueprint('user_bp', __name__)


def _allowed_file(filename: str) -> bool:
    allowed = current_app.config.get("UPLOAD_ALLOWED_EXTENSIONS") or set()
    return "." in filename and filename.rsplit(".", 1)[1].lower() in {ext.lower() for ext in allowed}


def _maybe_scan_file(file_path: str) -> None:
    # Hook for AV scanning; integrate with external service/CLI if available.
    # Currently a no-op to avoid blocking local dev.
    return


def _compute_financial_pulse(user):
    """Derive a simple financial health summary from the latest trial balance."""
    try:
        import datetime as _dt

        from finance_app.blueprints.accounting import tb_monthly  # type: ignore

        today = _dt.date.today()
        ym = f"{today.year}-{str(today.month).zfill(2)}"
        # Call the trial balance function directly to avoid a nested request context.
        flask_session["user_id"] = user.id  # ensure current_user resolves
        tb = tb_monthly(ym_override=ym)
        if not isinstance(tb, dict) or not tb.get("ok"):
            return None
        totals = tb.get("totals") or {}
        asset = float((totals.get("asset") or {}).get("balance") or 0.0)
        liability = float((totals.get("liability") or {}).get("balance") or 0.0)
        expense = float((totals.get("expense") or {}).get("period_debit") or 0.0)
        income = float((totals.get("income") or {}).get("period_credit") or 0.0)
        net = asset - liability
        burn = max(expense - income, 0.0)
        cash_months = (asset / burn) if burn > 0 else 12.0
        debt_ratio = liability / max(asset, 1.0)

        verdict = "healthy"
        summary = "Healthy buffer with manageable debt."
        recs = ["Keep a cushion of 3+ months cash.", "Invest or grow cautiously."]
        if cash_months < 1.0 or asset < liability * 0.3:
            verdict = "low_cash"
            summary = "Low on cash; prioritize liquidity and avoid new debt."
            recs = ["Delay discretionary spend.", "Accelerate collections.", "Avoid new borrowing until cash improves."]
        elif debt_ratio > 1.0:
            verdict = "debt_heavy"
            summary = "Debt load exceeds cash; focus on repayment."
            recs = ["Restructure or refinance costly debt.", "Pause new borrowing.", "Channel surplus to pay-down."]
        elif cash_months < 2.0:
            verdict = "watch"
            summary = "Thin buffer; monitor cash closely."
            recs = ["Trim expenses to reach 2-3 months runway.", "Schedule upcoming debt service early."]

        return {
            "verdict": verdict,
            "summary": summary,
            "recommendations": recs,
            "metrics": {
                "cash_on_hand": asset,
                "debt_total": liability,
                "net_position": net,
                "cash_months": cash_months,
                "debt_ratio": debt_ratio,
            },
            "ym": ym,
        }
    except Exception:
        return None


@user_bp.route('/profile', methods=['GET', 'POST'])
def profile():
    user = current_user()
    if not user:
        flash('Login required.')
        return redirect(url_for('auth_bp.login'))
    # Ensure profile exists
    if not user.profile:
        profile = UserProfile(user_id=user.id)
        db.session.add(profile)
        db.session.commit()
    profile = user.profile
    if request.method == 'POST':
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and file.filename:
                if not _allowed_file(file.filename):
                    flash('Unsupported file type.', 'danger')
                    return redirect(url_for('user_bp.profile'))
                filename = secure_filename(file.filename)
                upload_root = current_app.config.get("UPLOAD_FOLDER") or "instance/uploads"
                os.makedirs(upload_root, exist_ok=True)
                filepath = os.path.join(upload_root, filename)
                # Enforce size limit via stream length if provided
                if request.content_length and request.content_length > int(current_app.config.get("MAX_CONTENT_LENGTH") or 0):
                    flash('File exceeds size limit.', 'danger')
                    return redirect(url_for('user_bp.profile'))
                file.save(filepath)
                _maybe_scan_file(filepath)
                profile.profile_pic = filepath
        if 'notes' in request.form:
            profile.notes = request.form['notes']
        db.session.commit()
        flash('Profile updated.')
    posts = []
    admin_data = None
    if user.is_admin:
        total_users = User.query.count()
        total_non_admins = User.query.filter_by(is_admin=False).count()
        active_transactions = Transaction.query.count()
        pending_feedback = SuggestionFeedback.query.filter_by(is_correct=False).count()

        recent_sessions = (
            LoginSession.query.order_by(LoginSession.login_time.desc())
            .limit(5)
            .all()
        )
        flagged_feedback = (
            SuggestionFeedback.query.filter_by(is_correct=False)
            .order_by(SuggestionFeedback.timestamp.desc())
            .limit(5)
            .all()
        )
        user_ids = {s.user_id for s in recent_sessions} | {f.user_id for f in flagged_feedback}
        user_lookup = {}
        if user_ids:
            user_lookup = {
                u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()
            }
        recent_logins = []
        for session in recent_sessions:
            username = user_lookup.get(session.user_id).username if session.user_id in user_lookup else f'User #{session.user_id}'
            recent_logins.append({
                'username': username,
                'login': session.login_time.isoformat() if session.login_time else '',
                'logout': session.logout_time.isoformat() if session.logout_time else None
            })
        flagged_items = []
        for entry in flagged_feedback:
            username = user_lookup.get(entry.user_id).username if entry.user_id in user_lookup else f'User #{entry.user_id}'
            flagged_items.append({
                'username': username,
                'suggested': entry.suggested or 'N/A',
                'actual': entry.actual or 'N/A',
                'timestamp': entry.timestamp.isoformat() if entry.timestamp else ''
            })
        admin_data = {
            'hero_stats': {
                'users': total_users,
                'non_admins': total_non_admins,
                'transactions': active_transactions,
                'flags': pending_feedback
            },
            'recent_logins': recent_logins,
            'flagged_items': flagged_items
        }
    else:
        posts = UserPost.query.filter_by(profile_id=profile.id).order_by(UserPost.timestamp.desc()).all()

    def _entry_timestamp(entry):
        if getattr(entry, 'date_parsed', None):
            return entry.date_parsed
        date_str = getattr(entry, 'date', None)
        if not date_str:
            return None
        for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%Y.%m.%d', '%d-%m-%Y', '%Y/%m/%d'):
            try:
                return datetime.datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None

    ledger_count = JournalEntry.query.filter_by(user_id=user.id).count()
    latest_entry = (
        JournalEntry.query.filter_by(user_id=user.id)
        .order_by(JournalEntry.date_parsed.desc(), JournalEntry.date.desc(), JournalEntry.id.desc())
        .first()
    )

    if latest_entry and getattr(latest_entry, 'date_parsed', None):
        latest_entry_display = latest_entry.date_parsed.strftime('%Y/%m/%d')
    elif latest_entry and getattr(latest_entry, 'date', None):
        parsed = _entry_timestamp(latest_entry)
        latest_entry_display = parsed.strftime('%Y/%m/%d') if parsed else latest_entry.date
    else:
        latest_entry_display = 'No activity'
    financial_pulse = _compute_financial_pulse(user)

    return render_template(
        'profile.html',
        user=user,
        profile=profile,
        posts=posts,
        ledger_count=ledger_count,
        latest_entry_display=latest_entry_display,
        admin_data=admin_data,
        financial_pulse=financial_pulse,
    )


@user_bp.route('/profile/post', methods=['POST'])
def add_post():
    user = current_user()
    if not user or not user.profile:
        flash('Login required.')
        return redirect(url_for('auth_bp.login'))
    content = request.form.get('content', '').strip()
    if content:
        post = UserPost(profile_id=user.profile.id, content=content)
        db.session.add(post)
        db.session.commit()
        flash('Post added.')
    return redirect(url_for('user_bp.profile'))


@user_bp.route('/profile/post/edit/<int:post_id>', methods=['POST'])
def edit_post(post_id):
    user = current_user()
    post = UserPost.query.get_or_404(post_id)
    if not user or (not user.is_admin and (not user.profile or post.profile_id != user.profile.id)):
        flash('You do not have permission to edit this post.')
        return redirect(url_for('user_bp.profile'))
    new_content = request.form.get('content', '').strip()
    if not new_content:
        flash('Content cannot be empty.')
        return redirect(url_for('user_bp.profile'))
    post.content = new_content
    db.session.commit()
    flash('Post updated.')
    return redirect(url_for('user_bp.profile'))


@user_bp.route('/profile/change_credentials', methods=['GET', 'POST'])
def change_credentials():
    user = current_user()
    if not user:
        flash('Login required.')
        return redirect(url_for('auth_bp.login'))
    if request.method == 'POST':
        current_password = request.form.get('current_password', '').strip()
        if not current_password or not check_password_hash(user.password_hash, current_password):
            flash('Current password is incorrect.')
            return redirect(url_for('user_bp.change_credentials'))
        new_username = request.form.get('new_username', '').strip()
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        new_email = request.form.get('new_email', '').strip().lower()
        if new_username and new_username != user.username:
            if User.query.filter_by(username=new_username).first():
                flash('Username already exists.')
                return redirect(url_for('user_bp.change_credentials'))
            was_admin1 = (user.username == 'Admin1')
            user.username = new_username
            db.session.commit()
            if was_admin1:
                flash(f'Supervising account changed to {new_username}.')
        if new_password:
            if new_password != confirm_password:
                flash('Passwords do not match.')
                return redirect(url_for('user_bp.change_credentials'))
            if len(new_password) < 8:
                flash('Password must be at least 8 characters long.')
                return redirect(url_for('user_bp.change_credentials'))
            user.password_hash = generate_password_hash(new_password)
            db.session.commit()
            flash('Password updated.')
        if new_email and new_email != (user.email or ''):
            if '@' not in new_email or '.' not in new_email:
                flash('Please enter a valid email address.')
                return redirect(url_for('user_bp.change_credentials'))
            if User.query.filter(User.id != user.id, User.email == new_email).first():
                flash('Email is already in use by another account.')
                return redirect(url_for('user_bp.change_credentials'))
            user.email = new_email
            db.session.commit()
            flash('Email updated.')
        return redirect(url_for('user_bp.profile'))
    return render_template('change_credentials.html', user=user)


@user_bp.route('/profile/post/delete/<int:post_id>', methods=['POST'])
def delete_post(post_id):
    user = current_user()
    post = UserPost.query.get_or_404(post_id)
    if user and (user.is_admin or (user.profile and post.profile_id == user.profile.id)):
        db.session.delete(post)
        db.session.commit()
        flash('Post deleted.')
    else:
        flash('You do not have permission to delete this post.')
    return redirect(url_for('user_bp.profile'))
