"""
Trial Balance HTML -> PDF generator with WeasyPrint preferred and wkhtmltopdf fallback.

Usage (CLI):
  python -m trial_balance_pdf --data tb.json --org "Taeyang Finance" \
      --start 2025-01-01 --end 2025-12-31 --out out/trial_balance.pdf [--logo logo.png] [--engine auto|weasy|wkhtmltopdf]

Data format (example JSON):
{
  "rows": [
    {"group":"Asset","category":"Cash","currency":"KRW","bd":1200000.0,"debit":300000.0,"credit":150000.0},
    {"group":"Liability","category":"Payable","currency":"KRW","bd":0.0,"debit":0.0,"credit":50000.0}
  ],
  "totals": {"bd":1200000.0, "debit":300000.0, "credit":200000.0}
}

The generator computes net = debit - credit and ending balance = bd + net. Multi-currency is supported per row; currency
symbol defaults to KRW (₩) when not recognized.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from jinja2 import BaseLoader, Environment, select_autoescape


def _currency_symbol(code: str) -> str:
    code = (code or '').upper()
    return {
        'KRW': '₩',
        'MYR': 'RM',
        'CNY': '¥',
        'USD': '$',
        'EUR': '€',
        'JPY': '¥',
    }.get(code, '₩')


TB_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{{ org }} — Trial Balance ({{ period }})</title>
  <style>
    @page {
      size: A4;
      margin: 18mm;
      @top-center { content: element(page-header) }
      @bottom-center { content: element(page-footer) }
    }
    html, body { font-family: Inter, "Noto Sans KR", "Apple SD Gothic Neo", system-ui, -apple-system, Segoe UI, Roboto, sans-serif; font-size: 9pt; color: #111; }
    header.page-header { position: running(page-header); }
    footer.page-footer { position: running(page-footer); }
    .header-wrap { display:flex; align-items:center; justify-content:space-between; gap:8px; border-bottom: 1px solid #ddd; padding-bottom: 6px; margin-bottom: 10px; }
    .h-title { font-size: 12pt; font-weight: 700; }
    .h-sub { font-size: 9pt; color:#555; }
    .logo { max-height: 28px; max-width: 180px; object-fit: contain; }
    .footer-wrap { display:flex; align-items:center; justify-content:space-between; gap:8px; border-top: 1px solid #ddd; padding-top: 6px; margin-top: 10px; color:#666; font-size: 9pt; }

    table { width: 100%; border-collapse: collapse; }
    thead { display: table-header-group; }
    tfoot { display: table-row-group; }
    tr { page-break-inside: avoid; }
    th, td { border: 1px solid #ddd; padding: 6px 8px; }
    th { background: #f5f7fb; font-weight: 700; text-align: left; }
    td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
    tbody tr:nth-child(odd) { background: #fafbff; }
    .group { font-weight: 700; }
    .warn { background: #fff5f5; color: #b22222; border: 1px solid #f1c1c1; padding: 8px 10px; border-radius: 6px; margin: 8px 0; }

    .totals-row th { border-top: 2px solid #000; }
  </style>
</head>
<body>
  <header class="page-header">
    <div class="header-wrap">
      <div>
        <div class="h-title">{{ org }}</div>
        <div class="h-sub">Trial Balance — {{ period }}</div>
        <div class="h-sub" style="margin-top:4px;font-size:9pt;opacity:.8;">Prepared by Khairul Ammar Hakimi | 한태양 • {{ generated_at }}</div>
      </div>
      {% if logo %}
      <img class="logo" src="{{ logo }}" alt="logo" />
      {% endif %}
    </div>
  </header>

  {% if out_of_balance %}
    <div class="warn">Out of balance by {{ out_of_balance_str }}</div>
  {% endif %}

  <table>
    <thead>
      <tr>
        <th style="width:80px;">Group</th>
        <th style="width:15%;">Folder</th>
        <th style="width:25%;">Account</th>
        <th style="width:50px;">CCY</th>
        <th class="num" style="width:110px;">Beginning Balance</th>
        <th class="num" style="width:110px;">Period Debit</th>
        <th class="num" style="width:110px;">Period Credit</th>
        <th class="num" style="width:110px;">Net Change</th>
        <th class="num" style="width:120px;">Ending Balance</th>
      </tr>
    </thead>
    <tbody>
    {% for r in rows %}
      <tr>
        <td class="group">{{ r.group }}</td>
        <td>{{ r.category }}</td>
        <td>{{ r.account or '—' }}</td>
        <td style="text-align:center;">{{ r.currency }}</td>
        <td class="num">{{ r.bd_fmt }}</td>
        <td class="num">{{ r.debit_fmt }}</td>
        <td class="num">{{ r.credit_fmt }}</td>
        <td class="num">{{ r.net_fmt }}</td>
        <td class="num">{{ r.end_fmt }}</td>
      </tr>
    {% endfor %}
    </tbody>
    <tfoot>
      <tr class="totals-row">
        <th colspan="4" style="text-align:right;">Totals</th>
        <th class="num">{{ totals.bd_fmt }}</th>
        <th class="num">{{ totals.debit_fmt }}</th>
        <th class="num">{{ totals.credit_fmt }}</th>
        <th class="num">{{ totals.net_fmt }}</th>
        <th class="num">{{ totals.end_fmt }}</th>
      </tr>
    </tfoot>
  </table>

  <footer class="page-footer">
    <div class="footer-wrap">
      <div>Generated: {{ generated_at }}</div>
      <div>Page <span class="page-number"></span> of <span class="total-pages"></span></div>
    </div>
  </footer>

  <script>
    // For engines that support CSS counters (WeasyPrint), page numbers will be shown automatically.
  </script>
</body>
</html>
"""


def _format_amount(n: float, ccy: str) -> str:
    try:
        return f"{float(n):,.2f}" if abs(n) >= 1 else f"{float(n):,.2f}"
    except Exception:
        return "0"


def _prepare_rows(data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any], float]:
    rows = []
    totals = {"bd": 0.0, "debit": 0.0, "credit": 0.0, "net": 0.0, "end": 0.0}
    for r in data.get("rows", []):
        group = r.get("group") or ""
        category = r.get("category") or ""
        account = r.get("account") or ""
        ccy = (r.get("currency") or "KRW").upper()
        bd = float(r.get("bd") or 0.0)
        debit = float(r.get("debit") or 0.0)
        credit = float(r.get("credit") or 0.0)
        group_key = group.strip().lower()
        credit_balance = group_key in ("liability", "income")
        net = (credit - debit) if credit_balance else (debit - credit)
        end = bd + net
        rows.append({
            "group": group,
            "category": category,
            "currency": ccy,
            "account": account,
            "bd": bd, "debit": debit, "credit": credit, "net": net, "end": end,
            "bd_fmt": _format_amount(bd, ccy),
            "debit_fmt": _format_amount(debit, ccy),
            "credit_fmt": _format_amount(credit, ccy),
            "net_fmt": _format_amount(net, ccy),
            "end_fmt": _format_amount(end, ccy),
        })
        totals["bd"] += bd
        totals["debit"] += debit
        totals["credit"] += credit
        totals["net"] += net
        totals["end"] += end
    # Format totals using default KRW unless a single currency dominates; keep KRW default per spec
    t_ccy = "KRW"
    tf = {
        "bd_fmt": _format_amount(totals["bd"], t_ccy),
        "debit_fmt": _format_amount(totals["debit"], t_ccy),
        "credit_fmt": _format_amount(totals["credit"], t_ccy),
        "net_fmt": _format_amount(totals["net"], t_ccy),
        "end_fmt": _format_amount(totals["end"], t_ccy),
    }
    return rows, tf, totals["debit"] - totals["credit"]


def render_html(context: Dict[str, Any], template: str = TB_TEMPLATE) -> str:
    env = Environment(loader=BaseLoader(), autoescape=select_autoescape())
    tmpl = env.from_string(template)
    return tmpl.render(**context)


def render_with_weasyprint(html: str, out_pdf_path: Path) -> int:
    try:
        from weasyprint import HTML
    except Exception as e:
        raise RuntimeError(
            "WeasyPrint is not installed. Install with: pip install weasyprint\n"
            "Docs: https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation"
        ) from e
    try:
        doc = HTML(string=html, base_url=str(Path.cwd())).render()
        out_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        doc.write_pdf(target=str(out_pdf_path))
        return len(getattr(doc, 'pages', []) or [])
    except Exception as e:
        msg = (
            "WeasyPrint rendering failed. On macOS you may need native libs:\n"
            "  brew install pango cairo gdk-pixbuf libffi libxml2 libxslt harfbuzz fribidi librsvg\n"
            "See: https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation\n"
            "Error: " + str(e)
        )
        raise RuntimeError(msg) from e

def generate_trial_balance_pdf(
    data: Dict[str, Any],
    org: str,
    start_date: str,
    end_date: str,
    out_pdf: Path,
    logo: Optional[str] = None,
    engine: str = 'weasy',
) -> Tuple[int, str]:
    rows, totals_fmt, imbalance = _prepare_rows(data)
    period = f"{start_date} to {end_date}"
    ctx = {
        'org': org,
        'period': period,
        'generated_at': _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'rows': rows,
        'totals': totals_fmt,
        'out_of_balance': abs(imbalance) > 0.005,
        'out_of_balance_str': _format_amount(imbalance, 'KRW'),
        'logo': logo,
    }
    html = render_html(ctx)
    try:
        pages = render_with_weasyprint(html, out_pdf)
        return pages, _sha256_file(out_pdf)
    except Exception:
        # Surface a clear, WeasyPrint-only message
        raise


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description='Generate Trial Balance PDF')
    ap.add_argument('--data', required=True, help='Path to TB JSON')
    ap.add_argument('--org', required=True, help='Organization name')
    ap.add_argument('--start', required=True, help='Start date YYYY-MM-DD')
    ap.add_argument('--end', required=True, help='End date YYYY-MM-DD')
    ap.add_argument('--out', required=True, help='Output PDF file')
    ap.add_argument('--logo', default=None, help='Optional logo image path')
    ap.add_argument('--engine', default='weasy', choices=['weasy'], help='Rendering engine (weasy only).')
    args = ap.parse_args(argv)

    data = _load_json(Path(args.data))
    out_pdf = Path(args.out)
    pages, sha = generate_trial_balance_pdf(
        data=data,
        org=args.org,
        start_date=args.start,
        end_date=args.end,
        out_pdf=out_pdf,
        logo=args.logo,
    )
    print(str(out_pdf.resolve()))
    print(f"pages: {pages if pages else 'unknown'}")
    print(f"sha256: {sha}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
