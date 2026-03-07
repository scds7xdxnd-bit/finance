#!/usr/bin/env python3
"""
Lightweight smoke test to validate core routes and blueprint wiring.

Run:
  python3 scripts/smoke_test.py
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager

# Ensure ML is disabled for quick smoke runs
os.environ.setdefault('DISABLE_ML', '1')


@contextmanager
def app_ctx():
    """Load local app.py explicitly to avoid importing a different 'app' module."""
    import importlib.util
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Make project root importable so `import blueprints.*` in app.py works
    if base not in sys.path:
        sys.path.insert(0, base)
    # Also run in project root so relative paths resolve
    try:
        os.chdir(base)
    except Exception:
        pass
    app_py = os.path.join(base, 'app.py')
    spec = importlib.util.spec_from_file_location('finance_app_local', app_py)
    if spec is None or spec.loader is None:
        raise RuntimeError('Unable to locate local app.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules['finance_app_local'] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    app = getattr(module, 'app', None)
    if app is None:
        raise RuntimeError("Loaded app.py but couldn't find 'app' Flask instance")
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
