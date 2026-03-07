import datetime

from finance_app.extensions import db
from finance_app.lib.auth import _get_csrf_token
from finance_app.models.accounting_models import LoginSession
from finance_app.models.user_models import User
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

auth_bp = Blueprint('auth_bp', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        if not username or not password:
            flash('Username and password are required.')
            return render_template('login.html', csrf_token=_get_csrf_token())
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            try:
                login_session = LoginSession(user_id=user.id, login_time=datetime.datetime.utcnow())
                db.session.add(login_session)
                db.session.commit()
            except Exception:
                db.session.rollback()
                flash('Logged in, but session logging failed (check migrations).')
                return redirect(url_for('user_bp.profile'))
            flash('Logged in successfully.')
            return redirect(url_for('user_bp.profile'))
        else:
            flash('Invalid username or password.')
    return render_template('login.html', csrf_token=_get_csrf_token())


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form.get('email', '').strip().lower()
        if not email:
            flash('Email is required.')
            return render_template('register.html')
        if '@' not in email or '.' not in email:
            flash('Please enter a valid email address.')
            return render_template('register.html')
        if len(password) < 8:
            flash('Password must be at least 8 characters long.')
            return render_template('register.html')
        if User.query.filter_by(username=username).first():
            flash('Username already exists.')
            return render_template('register.html')
        if User.query.filter_by(email=email).first():
            flash('An account with that email already exists.')
            return render_template('register.html')
        is_admin = (username == 'Admin1')
        user = User(username=username, password_hash=generate_password_hash(password), email=email, is_admin=is_admin)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful. Please log in.')
        return redirect(url_for('auth_bp.login'))
    return render_template('register.html')


@auth_bp.route('/logout')
def logout():
    user_id = session.get('user_id')
    if user_id:
        latest_session = LoginSession.query.filter_by(user_id=user_id).order_by(LoginSession.login_time.desc()).first()
        if latest_session and not latest_session.logout_time:
            latest_session.logout_time = datetime.datetime.utcnow()
            db.session.commit()
        session.pop('user_id', None)
    flash('Logged out successfully.')
    return redirect(url_for('auth_bp.login'))


@auth_bp.route('/forgot-username', methods=['GET', 'POST'])
def forgot_username():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if not email:
            flash('Email is required.')
            return render_template('forgot_username.html')
        user = User.query.filter_by(email=email).first()
        if user:
            flash(f'Your username is: {user.username}')
        else:
            flash('If an account with that email exists, it will receive instructions.')
        return render_template('forgot_username.html')
    return render_template('forgot_username.html')


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        if not username or not email or not new_password:
            flash('All fields are required.')
            return render_template('forgot_password.html')
        user = User.query.filter_by(username=username, email=email).first()
        if not user:
            flash('Provided details do not match our records.')
            return render_template('forgot_password.html')
        if new_password != confirm_password:
            flash('Passwords do not match.')
            return render_template('forgot_password.html')
        if len(new_password) < 8:
            flash('Password must be at least 8 characters long.')
            return render_template('forgot_password.html')
        user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        flash('Password has been reset. You can now log in.')
        return redirect(url_for('auth_bp.login'))
    return render_template('forgot_password.html')
