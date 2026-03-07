import datetime


def _parse_date_tuple(d: str):
    """Parse flexible date strings like YYYY/MM/DD or YYYY/M/D into sortable tuple."""
    try:
        if not d:
            return (0, 0, 0)
        s = d.replace("-", "/").strip()
        parts = s.split("/")
        if len(parts) != 3:
            return (0, 0, 0)
        y, m, da = [int(p) for p in parts]
        return (y, m, da)
    except Exception:
        return (0, 0, 0)


def _normalize_date_for_ml(date_str: str) -> str:
    """Convert user-provided date into ISO format expected by ML service."""
    y, m, d = _parse_date_tuple(date_str or "")
    if y and m and d:
        try:
            return datetime.date(y, m, d).isoformat()
        except Exception:
            pass
    try:
        return datetime.date.fromisoformat((date_str or "").split("T")[0]).isoformat()
    except Exception:
        return datetime.date.today().isoformat()
