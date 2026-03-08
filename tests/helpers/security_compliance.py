from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from finance_app import db
from finance_app.models.accounting_models import AdminActionAudit
from finance_app.models.money_account import AccountType, MoneyScheduleAccount
from finance_app.models.user_models import User

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SSOT_PATH = ROOT / "project" / "docs" / "ssot" / "70_security_model.md"
DEFAULT_EXCEPTION_SNAPSHOT_PATH = ROOT / "tests" / "fixtures" / "security_exception_register_snapshot.json"
REQUIRED_EXCEPTION_COLUMNS = (
    "exception_id",
    "method",
    "path",
    "missing_controls",
    "required_end_state",
    "expires_on_utc",
    "status",
)
VALID_EXCEPTION_STATUS = {"open", "closed"}


@dataclass(frozen=True)
class SecurityExceptionRow:
    exception_id: str
    method: str
    path: str
    missing_controls: tuple[str, ...]
    required_end_state: str
    expires_on_utc: dt.date
    status: str


def _normalize_today(today_utc: dt.date | str | None = None) -> dt.date:
    if today_utc is None:
        return dt.datetime.now(dt.timezone.utc).date()
    if isinstance(today_utc, dt.date):
        return today_utc
    return dt.date.fromisoformat(str(today_utc))


def _parse_markdown_row(line: str) -> list[str]:
    trimmed = line.strip()
    if not (trimmed.startswith("|") and trimmed.endswith("|")):
        raise ValueError(f"Invalid markdown table row: {line}")
    return [cell.strip() for cell in trimmed.strip("|").split("|")]


def _parse_missing_controls(raw: str) -> tuple[str, ...]:
    controls = [
        token.strip().strip("`").lower()
        for token in str(raw or "").split(",")
        if token.strip().strip("`")
    ]
    return tuple(sorted(set(controls)))


def _concrete_path(path_template: str) -> str:
    def _repl(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.startswith("<path:"):
            return "sample"
        return "1"

    return re.sub(r"<[^>]+>", _repl, path_template)


def _path_matches(path_template: str, probe_path: str) -> bool:
    escaped = re.escape(path_template)
    pattern = re.sub(r"\\<[^>]+\\>", r"[^/]+", escaped)
    return re.fullmatch(pattern, probe_path) is not None


def _auth_rejected(response) -> bool:
    if response.status_code in (401, 403):
        return True
    if response.status_code in (301, 302, 303, 307, 308):
        location = str(response.headers.get("Location") or "")
        return "/login" in location
    return False


def _csrf_rejected(response) -> bool:
    body = response.get_data(as_text=True).lower()
    return response.status_code == 400 and "csrf token missing or invalid" in body


def parse_exception_register(markdown_text: str) -> list[SecurityExceptionRow]:
    lines = markdown_text.splitlines()
    header_idx = None
    for idx, line in enumerate(lines):
        if line.strip().startswith("| exception_id |"):
            header_idx = idx
            break
    if header_idx is None:
        raise ValueError("SSOT 70.5 exception register header not found")

    header_cols = _parse_markdown_row(lines[header_idx])
    if tuple(header_cols) != REQUIRED_EXCEPTION_COLUMNS:
        raise ValueError(
            "SSOT 70.5 exception register columns mismatch: "
            f"expected={list(REQUIRED_EXCEPTION_COLUMNS)} observed={header_cols}"
        )

    rows: list[SecurityExceptionRow] = []
    for line in lines[header_idx + 1 :]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        if set(stripped.replace("|", "").strip()) <= {"-", " ", ":"}:
            continue

        cells = _parse_markdown_row(stripped)
        if len(cells) != len(REQUIRED_EXCEPTION_COLUMNS):
            raise ValueError(f"SSOT 70.5 row has invalid column count: {cells}")

        row_map = dict(zip(REQUIRED_EXCEPTION_COLUMNS, cells, strict=True))
        status = str(row_map["status"]).strip().lower()
        if status not in VALID_EXCEPTION_STATUS:
            raise ValueError(
                f"SSOT 70.5 row has invalid status for {row_map['exception_id']}: {row_map['status']}"
            )

        expires_raw = str(row_map["expires_on_utc"]).strip()
        try:
            expires = dt.date.fromisoformat(expires_raw)
        except ValueError as exc:
            raise ValueError(
                f"SSOT 70.5 row has invalid expires_on_utc for {row_map['exception_id']}: {expires_raw}"
            ) from exc

        rows.append(
            SecurityExceptionRow(
                exception_id=str(row_map["exception_id"]).strip(),
                method=str(row_map["method"]).strip().upper(),
                path=str(row_map["path"]).strip().strip("`").strip(),
                missing_controls=_parse_missing_controls(row_map["missing_controls"]),
                required_end_state=str(row_map["required_end_state"]).strip(),
                expires_on_utc=expires,
                status=status,
            )
        )

    if not rows:
        raise ValueError("SSOT 70.5 exception register has no rows")
    return rows


def load_exception_register(ssot_path: str | Path = DEFAULT_SSOT_PATH) -> list[SecurityExceptionRow]:
    path = Path(ssot_path)
    return parse_exception_register(path.read_text(encoding="utf-8"))


def build_exception_snapshot(rows: list[SecurityExceptionRow]) -> dict[str, Any]:
    exceptions = sorted(
        [{"exception_id": row.exception_id, "status": row.status} for row in rows],
        key=lambda item: str(item["exception_id"]),
    )
    open_exception_ids = sorted([row.exception_id for row in rows if row.status == "open"])
    return {
        "snapshot_version": 1,
        "source": "project/docs/ssot/70_security_model.md#70.5",
        "exceptions": exceptions,
        "open_exception_ids": open_exception_ids,
    }


def load_exception_snapshot(
    snapshot_path: str | Path = DEFAULT_EXCEPTION_SNAPSHOT_PATH,
) -> dict[str, Any]:
    path = Path(snapshot_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Security exception snapshot must be a JSON object")
    exceptions = data.get("exceptions")
    if not isinstance(exceptions, list):
        raise ValueError("Security exception snapshot must include list field: exceptions")
    for entry in exceptions:
        if not isinstance(entry, dict):
            raise ValueError("Security exception snapshot exceptions entries must be objects")
        if "exception_id" not in entry or "status" not in entry:
            raise ValueError("Security exception snapshot entry missing required keys: exception_id/status")
    return data


def detect_exception_snapshot_drift(
    rows: list[SecurityExceptionRow],
    snapshot: dict[str, Any],
) -> dict[str, list[str]]:
    current_status_by_id = {row.exception_id: row.status for row in rows}
    snapshot_status_by_id = {
        str(entry.get("exception_id")): str(entry.get("status", "")).strip().lower()
        for entry in (snapshot.get("exceptions") or [])
        if isinstance(entry, dict) and entry.get("exception_id")
    }

    new_exception_ids = sorted(set(current_status_by_id) - set(snapshot_status_by_id))
    reopened_exception_ids = sorted(
        [
            exc_id
            for exc_id, cur_status in current_status_by_id.items()
            if exc_id in snapshot_status_by_id
            and cur_status == "open"
            and snapshot_status_by_id.get(exc_id) not in {"", "open"}
        ]
    )
    new_open_exception_ids = sorted([exc_id for exc_id in new_exception_ids if current_status_by_id.get(exc_id) == "open"])

    return {
        "new_exception_ids": new_exception_ids,
        "reopened_exception_ids": reopened_exception_ids,
        "new_open_exception_ids": new_open_exception_ids,
    }


def has_active_exception(
    rows: list[SecurityExceptionRow],
    *,
    method: str,
    path: str,
    control: str,
    today_utc: dt.date | str | None = None,
) -> bool:
    today = _normalize_today(today_utc)
    method_u = method.strip().upper()
    control_l = control.strip().lower()
    for row in rows:
        if row.status != "open" or today > row.expires_on_utc:
            continue
        if row.method != method_u:
            continue
        if not (_path_matches(row.path, path) or _path_matches(path, row.path)):
            continue
        if control_l in row.missing_controls:
            return True
    return False


def expired_exception_ids(
    rows: list[SecurityExceptionRow],
    *,
    today_utc: dt.date | str | None = None,
) -> list[str]:
    today = _normalize_today(today_utc)
    return sorted(
        [
            row.exception_id
            for row in rows
            if row.status == "open" and today > row.expires_on_utc
        ]
    )


def probe_exception_route_controls(app, rows: list[SecurityExceptionRow]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    rule_set = {
        (method, rule.rule)
        for rule in app.url_map.iter_rules()
        for method in (rule.methods or set())
    }
    client = app.test_client()

    for row in rows:
        controls = [c for c in row.missing_controls if c in {"csrf", "auth", "scope"}]
        if not controls:
            continue
        if row.path in {"/forecast", "/api/forecast.json", "/forecast/schedule"}:
            # Forecast routes are handled by dedicated Option A probe logic.
            continue

        route_exists = (row.method, row.path) in rule_set
        probe_path = _concrete_path(row.path)

        kwargs: dict[str, Any] = {"follow_redirects": False}
        if row.method == "POST":
            if row.path == "/journal_feedback":
                kwargs["json"] = {"accepted": True, "suggestion": {"label": "test"}}
            else:
                kwargs["data"] = {}

        resp = client.open(probe_path, method=row.method, **kwargs)
        enforced = {
            "csrf": _csrf_rejected(resp),
            "auth": _auth_rejected(resp),
            # Scope generally depends on authenticated identity context.
            # For transition gating, auth rejection is the minimum owner-scope precursor.
            "scope": _auth_rejected(resp),
        }

        for control in controls:
            if enforced.get(control):
                continue
            violations.append(
                {
                    "method": row.method,
                    "path": row.path,
                    "control": control,
                    "route_exists": route_exists,
                    "status_code": resp.status_code,
                }
            )

    return violations


def probe_logout_method_safety(app) -> dict[str, Any]:
    client = app.test_client()
    with app.app_context():
        user = User(username=f"logout_probe_{uuid4().hex}", password_hash="pw", is_admin=False)
        db.session.add(user)
        db.session.commit()
        user_id = int(user.id)

    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["csrf_token"] = "logout-csrf"

    get_resp = client.get("/logout", follow_redirects=False)
    with client.session_transaction() as sess:
        still_logged_in = int(sess.get("user_id") or 0) == user_id

    post_methods = [
        rule
        for rule in app.url_map.iter_rules()
        if rule.rule == "/logout" and "POST" in (rule.methods or set())
    ]
    post_supported = bool(post_methods)
    post_status = None
    if post_supported:
        post_resp = client.post("/logout", headers={"X-CSRF-Token": "logout-csrf"}, follow_redirects=False)
        post_status = post_resp.status_code

    return {
        "get_status_code": get_resp.status_code,
        "get_logs_out_without_csrf": not still_logged_in,
        "post_route_available": post_supported,
        "post_with_csrf_status": post_status,
    }


def _login(client, user_id: int, csrf_token: str) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
        sess["csrf_token"] = csrf_token


def probe_forecast_option_a(app) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    original_flag = app.config.get("FORECAST_LEGACY_ENABLED")

    with app.app_context():
        admin = User(username=f"forecast_admin_{uuid4().hex}", password_hash="pw", is_admin=True)
        non_admin = User(username=f"forecast_user_{uuid4().hex}", password_hash="pw", is_admin=False)
        account = MoneyScheduleAccount(
            name=f"Forecast Probe {uuid4().hex[:8]}",
            type=AccountType.CHECKING,
            currency="KRW",
            current_balance=0,
            is_included_in_closing=True,
        )
        db.session.add_all([admin, non_admin, account])
        db.session.commit()
        admin_id = int(admin.id)
        non_admin_id = int(non_admin.id)
        account_id = int(account.id)

    schedule_form = {
        "description": "probe",
        "amount": "1",
        "date": dt.date.today().isoformat(),
        "account_id": str(account_id),
        "currency": "KRW",
    }

    def _open_status(client, method: str, path: str, **kwargs) -> int:
        try:
            response = client.open(path, method=method, **kwargs)
            return int(response.status_code)
        except Exception:
            return 500

    try:
        app.config["FORECAST_LEGACY_ENABLED"] = False
        disabled_client = app.test_client()
        for method, path in (
            ("GET", "/forecast"),
            ("GET", "/api/forecast.json"),
            ("POST", "/forecast/schedule"),
        ):
            if method == "GET":
                status_code = _open_status(disabled_client, "GET", path, follow_redirects=False)
            else:
                status_code = _open_status(
                    disabled_client,
                    "POST",
                    path,
                    data=schedule_form,
                    follow_redirects=False,
                )
            if status_code != 404:
                control = "admin_fence" if method == "GET" else "auth"
                violations.append(
                    {
                        "method": method,
                        "path": path,
                        "control": control,
                        "detail": f"disabled_mode_expected_404_got_{status_code}",
                    }
                )

        app.config["FORECAST_LEGACY_ENABLED"] = True

        unauth = app.test_client()
        non_admin = app.test_client()
        admin = app.test_client()
        _login(non_admin, non_admin_id, csrf_token="forecast-user-csrf")
        _login(admin, admin_id, csrf_token="forecast-admin-csrf")

        for path in ("/forecast", "/api/forecast.json"):
            unauth_status = _open_status(unauth, "GET", path, follow_redirects=False)
            if unauth_status != 401:
                violations.append(
                    {
                        "method": "GET",
                        "path": path,
                        "control": "auth",
                        "detail": f"enabled_mode_unauth_expected_401_got_{unauth_status}",
                    }
                )

            non_admin_status = _open_status(non_admin, "GET", path, follow_redirects=False)
            if non_admin_status != 403:
                violations.append(
                    {
                        "method": "GET",
                        "path": path,
                        "control": "admin_fence",
                        "detail": f"enabled_mode_non_admin_expected_403_got_{non_admin_status}",
                    }
                )

            admin_status = _open_status(admin, "GET", path, follow_redirects=False)
            if admin_status != 200:
                violations.append(
                    {
                        "method": "GET",
                        "path": path,
                        "control": "admin_fence",
                        "detail": f"enabled_mode_admin_expected_200_got_{admin_status}",
                    }
                )

        unauth_post = _open_status(
            unauth,
            "POST",
            "/forecast/schedule",
            data=schedule_form,
            follow_redirects=False,
        )
        if unauth_post != 401:
            violations.append(
                {
                    "method": "POST",
                    "path": "/forecast/schedule",
                    "control": "auth",
                    "detail": f"enabled_mode_schedule_unauth_expected_401_got_{unauth_post}",
                }
            )

        non_admin_post = _open_status(
            non_admin,
            "POST",
            "/forecast/schedule",
            data=schedule_form,
            follow_redirects=False,
        )
        if non_admin_post != 403:
            violations.append(
                {
                    "method": "POST",
                    "path": "/forecast/schedule",
                    "control": "admin",
                    "detail": f"enabled_mode_schedule_non_admin_expected_403_got_{non_admin_post}",
                }
            )

        admin_missing_csrf = _open_status(
            admin,
            "POST",
            "/forecast/schedule",
            data=schedule_form,
            follow_redirects=False,
        )
        if admin_missing_csrf != 400:
            violations.append(
                {
                    "method": "POST",
                    "path": "/forecast/schedule",
                    "control": "csrf",
                    "detail": f"enabled_mode_schedule_admin_missing_csrf_expected_400_got_{admin_missing_csrf}",
                }
            )

        with app.app_context():
            audit_before = int(AdminActionAudit.query.count())

        admin_with_csrf = _open_status(
            admin,
            "POST",
            "/forecast/schedule",
            data=schedule_form,
            headers={"X-CSRF-Token": "forecast-admin-csrf"},
            follow_redirects=False,
        )

        with app.app_context():
            audit_after = int(AdminActionAudit.query.count())

        if audit_after <= audit_before:
            violations.append(
                {
                    "method": "POST",
                    "path": "/forecast/schedule",
                    "control": "audit",
                    "detail": "enabled_mode_schedule_admin_audit_not_written",
                }
            )

        if admin_with_csrf != 503:
            violations.append(
                {
                    "method": "POST",
                    "path": "/forecast/schedule",
                    "control": "schema_guard",
                    "detail": (
                        "enabled_mode_schedule_admin_schema_guard_expected_503_when_capability_missing_"
                        f"got_{admin_with_csrf}"
                    ),
                }
            )
    finally:
        app.config["FORECAST_LEGACY_ENABLED"] = original_flag

    return violations


def security_failure_message(payload: dict[str, Any]) -> str:
    return (
        "Security compliance gate failed: "
        f"new_exception_ids={payload.get('new_exception_ids') or []} "
        f"reopened_exception_ids={payload.get('reopened_exception_ids') or []} "
        f"new_open_exception_ids={payload.get('new_open_exception_ids') or []} "
        f"expired_exception_ids={payload.get('expired_exception_ids') or []} "
        f"missing_csrf_routes={payload.get('missing_csrf_routes') or []} "
        f"missing_auth_routes={payload.get('missing_auth_routes') or []} "
        f"missing_scope_routes={payload.get('missing_scope_routes') or []} "
        f"method_safety_failures={payload.get('method_safety_failures') or []} "
        f"forecast_fence_failures={payload.get('forecast_fence_failures') or []}"
    )


def evaluate_security_compliance(
    app,
    *,
    ssot_path: str | Path = DEFAULT_SSOT_PATH,
    snapshot_path: str | Path = DEFAULT_EXCEPTION_SNAPSHOT_PATH,
    today_utc: dt.date | str | None = None,
) -> dict[str, Any]:
    rows = load_exception_register(ssot_path)
    snapshot = load_exception_snapshot(snapshot_path)
    snapshot_drift = detect_exception_snapshot_drift(rows, snapshot)
    today = _normalize_today(today_utc)

    payload: dict[str, Any] = {
        "ok": True,
        "today_utc": today.isoformat(),
        "exception_count": len(rows),
        "new_exception_ids": sorted(snapshot_drift["new_exception_ids"]),
        "reopened_exception_ids": sorted(snapshot_drift["reopened_exception_ids"]),
        "new_open_exception_ids": sorted(snapshot_drift["new_open_exception_ids"]),
        "expired_exception_ids": expired_exception_ids(rows, today_utc=today),
        "missing_csrf_routes": [],
        "missing_auth_routes": [],
        "missing_scope_routes": [],
        "method_safety_failures": [],
        "forecast_fence_failures": [],
    }

    route_violations = probe_exception_route_controls(app, rows)
    missing_csrf_routes: set[str] = set()
    missing_auth_routes: set[str] = set()
    missing_scope_routes: set[str] = set()

    for violation in route_violations:
        method = str(violation["method"])
        path = str(violation["path"])
        control = str(violation["control"])
        if has_active_exception(rows, method=method, path=path, control=control, today_utc=today):
            continue
        route_label = f"{method} {path}"
        if control == "csrf":
            missing_csrf_routes.add(route_label)
        elif control == "auth":
            missing_auth_routes.add(route_label)
        elif control == "scope":
            missing_scope_routes.add(route_label)

    logout_probe = probe_logout_method_safety(app)
    method_safety_failures: set[str] = set()
    if logout_probe.get("get_logs_out_without_csrf") and not has_active_exception(
        rows,
        method="GET",
        path="/logout",
        control="method_safety",
        today_utc=today,
    ):
        method_safety_failures.add("GET /logout logs out without CSRF")

    if bool(logout_probe.get("post_route_available")) and int(logout_probe.get("post_with_csrf_status") or 500) >= 400:
        if not has_active_exception(rows, method="GET", path="/logout", control="method_safety", today_utc=today):
            method_safety_failures.add("POST /logout with CSRF does not succeed")

    forecast_violations = probe_forecast_option_a(app)
    forecast_failures: set[str] = set()
    for violation in forecast_violations:
        method = str(violation["method"])
        path = str(violation["path"])
        control = str(violation["control"])
        detail = str(violation.get("detail") or f"{method} {path} {control}")
        if has_active_exception(rows, method=method, path=path, control=control, today_utc=today):
            continue
        forecast_failures.add(detail)

    payload["missing_csrf_routes"] = sorted(missing_csrf_routes)
    payload["missing_auth_routes"] = sorted(missing_auth_routes)
    payload["missing_scope_routes"] = sorted(missing_scope_routes)
    payload["method_safety_failures"] = sorted(method_safety_failures)
    payload["forecast_fence_failures"] = sorted(forecast_failures)

    payload["ok"] = not any(
        [
            payload["new_exception_ids"],
            payload["reopened_exception_ids"],
            payload["new_open_exception_ids"],
            payload["expired_exception_ids"],
            payload["missing_csrf_routes"],
            payload["missing_auth_routes"],
            payload["missing_scope_routes"],
            payload["method_safety_failures"],
            payload["forecast_fence_failures"],
        ]
    )
    if not payload["ok"]:
        payload["message"] = security_failure_message(payload)

    return payload
