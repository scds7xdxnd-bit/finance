#!/usr/bin/env python3
"""Lightweight smoke test to validate core routes and blueprint wiring.

Run:
  python3 scripts/smoke_test.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from contextlib import contextmanager

# Ensure ML is disabled for quick smoke runs
os.environ.setdefault('DISABLE_ML', '1')
# Ensure fresh CI environments can serve routes without a pre-migrated DB.
os.environ.setdefault('AUTO_CREATE_SCHEMA', 'true')


@contextmanager
def app_ctx():
    """Build the Flask app from finance_app factory in this repository."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Make project root importable so `import blueprints.*` resolves locally.
    if base not in sys.path:
        sys.path.insert(0, base)
    # Run in project root so relative paths resolve.
    try:
        os.chdir(base)
    except Exception:
        pass

    # Use an isolated throwaway sqlite DB for smoke runs.
    with tempfile.TemporaryDirectory(prefix='finance_smoke_') as tmpdir:
        db_path = os.path.join(tmpdir, 'smoke.db')
        os.environ.setdefault('FINANCE_DATABASE_URL', f"sqlite:///{db_path}")
        os.environ.setdefault('ALEMBIC_DATABASE_URL', f"sqlite:///{db_path}")

        from finance_app import create_app

        app = create_app()
        app.config.update(TESTING=True)
        with app.app_context():
            yield app


def expect(status, got, where):
    assert got == status, f"Expected {status} at {where}, got {got}"


def main():
    with app_ctx() as app:
        client = app.test_client()

        # Index should redirect to login when anonymous
        r = client.get('/')
        expect(302, r.status_code, '/')
        assert '/login' in r.location, f"Index redirect should go to login, got {r.location}"

        # Login page renders
        r = client.get('/login')
        expect(200, r.status_code, '/login')
        assert b'Login' in r.data

        # Accounting redirects to login when anonymous
        r = client.get('/accounting')
        expect(302, r.status_code, '/accounting')
        assert '/login' in r.location

        # Transactions redirects to login when anonymous
        r = client.get('/transactions')
        expect(302, r.status_code, '/transactions')
        assert '/login' in r.location

        # Admin redirects to login when anonymous
        r = client.get('/admin')
        expect(302, r.status_code, '/admin')
        assert '/login' in r.location

        # Print a brief summary
        print('Smoke OK. Routes:', len(list(app.url_map.iter_rules())))


if __name__ == '__main__':
    try:
        main()
    except AssertionError as e:
        print('Smoke failed:', e)
        sys.exit(1)
    except Exception as e:
        print('Unexpected error:', e)
        sys.exit(2)
