"""
Financial Statements (Income Statement, Balance Sheet, Cash Flow) HTML -> PDF using WeasyPrint.
Design aligns with trial_balance_pdf (A4, header/footer, small fonts, zebra tables).
"""
from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Sequence, Set, Tuple

from finance_app.services.exchange_rate_service import get_rate_to_krw
from jinja2 import BaseLoader, Environment, select_autoescape
from trial_balance_pdf import render_with_weasyprint  # reuse renderer

BASE_CSS = """
  @page { size:A4; margin:18mm; @top-center { content: element(page-header) } @bottom-center { content: element(page-footer) } }
  html, body { font-family: Inter, "Noto Sans KR", "Apple SD Gothic Neo", system-ui, -apple-system, Segoe UI, Roboto, sans-serif; font-size: 9pt; color:#111; }
  header.page-header { position: running(page-header); }
  footer.page-footer { position: running(page-footer); }
  .header-wrap { display:flex; align-items:center; justify-content:space-between; gap:8px; border-bottom: 1px solid #ddd; padding-bottom: 6px; margin-bottom: 10px; }
  .h-title { font-size: 12pt; font-weight: 700; }
  .h-sub { font-size: 9pt; color:#555; }
  .logo { max-height: 28px; max-width: 180px; object-fit: contain; }
  .footer-wrap { display:flex; align-items:center; justify-content:space-between; gap:8px; border-top: 1px solid #ddd; padding-top: 6px; margin-top: 10px; color:#666; font-size: 9pt; }
  .page-number:before { content: counter(page); }
  .total-pages:before { content: counter(pages); }
  main.statement-body { display:flex; flex-direction:column; gap:12px; }
  .statement-title { text-align:center; margin:8px 0 12px; }
  .statement-title .eyebrow { font-size:9pt; text-transform:uppercase; letter-spacing:0.12em; color:#374151; }
  .statement-title .period { font-size:12pt; font-weight:700; margin-top:4px; }
  table { width:100%; border-collapse: collapse; }
  thead { display: table-header-group; }
  tr { page-break-inside: avoid; }
  table.income-table { font-variant-numeric: tabular-nums; }
  table.income-table th { text-align:right; border-bottom:1px solid #111; padding:6px 8px; }
  table.income-table th.desc { text-align:left; font-weight:600; }
  table.income-table td { padding:4px 6px; border-bottom:1px solid #e5e7eb; }
  td.num, th.num { text-align:right; }
  td.desc { text-align:left; }
  .section-row td { border-bottom:none; padding-top:10px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; }
  .line-item td { font-weight:600; color:#111; }
  .account-row td { font-size:8pt; color:#4b5563; border-bottom:1px solid #f3f4f6; }
  .account-row td.desc { padding-left:16px; }
  .subtotal-row td { font-weight:700; border-top:1px solid #111; border-bottom:1px solid #e5e7eb; padding-top:6px; }
  .net-row td { font-weight:700; border-top:2px solid #111; font-size:10pt; padding-top:8px; }
"""


IS_TEMPLATE = r"""
<!DOCTYPE html><html><head><meta charset="utf-8"><title>{{ org }} — Income Statement ({{ period }})</title>
<style>{{ base_css }}</style></head><body>
<header class="page-header"><div class="header-wrap"><div><div class="h-title">{{ org }}</div><div class="h-sub">Income Statement — {{ period }}</div><div class="h-sub" style="margin-top:4px;opacity:.8;">Prepared by Khairul Ammar Hakimi | 한태양 • {{ generated_at }}</div></div>{% if logo %}<img class="logo" src="{{ logo }}"/>{% endif %}</div></header>
<main class="statement-body">
  {% macro amount_cell(row, column) -%}
    {%- if column == '__BASE__' -%}
      {{ row.amt_fmt }}
    {%- else -%}
      {%- set currencies = row.currencies or {} -%}
      {%- set entry = currencies.get(column) -%}
      {{ entry.fmt if entry else '—' }}
    {%- endif -%}
  {%- endmacro %}
  {% macro total_cell(kind, column) -%}
    {%- if column == '__BASE__' -%}
      {{ totals[kind ~ '_fmt'] }}
    {%- else -%}
      {%- set entry = currency_totals_map.get(column) -%}
      {{ entry[kind ~ '_fmt'] if entry else '—' }}
    {%- endif -%}
  {%- endmacro %}
  {% macro account_rows(row, columns) -%}
    {%- set details = row.account_details or {} -%}
    {%- for currency in columns -%}
      {%- if currency == '__BASE__' -%}
        {%- set accounts = [] -%}
      {%- else -%}
        {%- set accounts = details.get(currency) or [] -%}
      {%- endif -%}
      {%- for acc in accounts -%}
        <tr class="account-row">
          <td class="desc">• {{ acc.name }}</td>
          {%- for col in columns -%}
            <td class="num">{% if col == currency %}{{ acc.fmt }}{% else %}—{% endif %}</td>
          {%- endfor -%}
        </tr>
      {%- endfor -%}
    {%- endfor -%}
  {%- endmacro %}
  <section class="statement-title">
    <div class="eyebrow">Income Statement as of</div>
    <div class="period">{{ end_date }}</div>
  </section>
  <table class="income-table">
    <thead>
      <tr>
        <th class="desc"></th>
        {% for col in column_keys %}
        <th class="num">{{ column_labels[col] }}</th>
        {% endfor %}
      </tr>
    </thead>
    <tbody>
      <tr class="section-row"><td class="desc">Income</td><td colspan="{{ column_keys|length }}"></td></tr>
      {% for row in income_rows %}
      <tr class="line-item">
        <td class="desc">{{ row.name }}</td>
        {% for col in column_keys %}
        <td class="num">{{ amount_cell(row, col) }}</td>
        {% endfor %}
      </tr>
      {{ account_rows(row, column_keys) | safe }}
      {% endfor %}
      <tr class="subtotal-row">
        <td class="desc">Total Income</td>
        {% for col in column_keys %}<td class="num">{{ total_cell('revenue', col) }}</td>{% endfor %}
      </tr>
      <tr class="section-row"><td class="desc">Expenses</td><td colspan="{{ column_keys|length }}"></td></tr>
      {% for row in expense_rows %}
      <tr class="line-item">
        <td class="desc">{{ row.name }}</td>
        {% for col in column_keys %}
        <td class="num">{{ amount_cell(row, col) }}</td>
        {% endfor %}
      </tr>
      {{ account_rows(row, column_keys) | safe }}
      {% endfor %}
      <tr class="subtotal-row">
        <td class="desc">Total Expenses</td>
        {% for col in column_keys %}<td class="num">{{ total_cell('expense', col) }}</td>{% endfor %}
      </tr>
      <tr class="net-row">
        <td class="desc">Net Income</td>
        {% for col in column_keys %}<td class="num">{{ total_cell('net_income', col) }}</td>{% endfor %}
      </tr>
    </tbody>
  </table>
</main>
<footer class="page-footer"><div class="footer-wrap"><div>Generated: {{ generated_at }}</div><div>Page <span class="page-number"></span> of <span class="total-pages"></span></div></div></footer>
</body></html>
"""

BS_TEMPLATE = r"""
<!DOCTYPE html><html><head><meta charset="utf-8"><title>{{ org }} — Balance Sheet ({{ period }})</title>
<style>{{ base_css }}</style></head><body>
<header class="page-header"><div class="header-wrap"><div><div class="h-title">{{ org }}</div><div class="h-sub">Statement of Financial Position — {{ period }}</div><div class="h-sub" style="margin-top:4px;opacity:.8;">Prepared by Khairul Ammar Hakimi | 한태양 • {{ generated_at }}</div></div>{% if logo %}<img class="logo" src="{{ logo }}"/>{% endif %}</div></header>
<main class="statement-body">
  {% set section_field_map = {'asset': 'assets_fmt', 'liability': 'liabilities_fmt', 'equity': 'equity_fmt', 'le': 'le_sum_fmt'} %}
  {% set show_accounts = column_keys|length == 1 and column_keys[0] != '__BASE__' %}
  {% macro amount_cell(row, column) -%}
    {%- if column == '__BASE__' -%}
      {{ row.amt_fmt }}
    {%- else -%}
      {%- set entry = row.currencies.get(column) -%}
      {{ entry.fmt if entry else '—' }}
    {%- endif -%}
  {%- endmacro %}
  {% macro total_cell(section_key, column) -%}
    {%- if column == '__BASE__' -%}
      {%- set field = section_field_map.get(section_key) -%}
      {{ totals[field] if field else '' }}
    {%- else -%}
      {%- set entry = currency_totals_map.get(column) -%}
      {%- if section_key == 'asset' -%}
        {{ entry.assets_fmt if entry else '—' }}
      {%- elif section_key == 'liability' -%}
        {{ entry.liabilities_fmt if entry else '—' }}
      {%- elif section_key == 'equity' -%}
        {{ entry.equity_fmt if entry else '—' }}
      {%- elif section_key == 'le' -%}
        {{ entry.le_sum_fmt if entry else '—' }}
      {%- endif -%}
    {%- endif -%}
  {%- endmacro %}
  {% macro account_rows(row, columns, enabled) -%}
    {%- if enabled -%}
      {%- for currency, accounts in (row.account_details or {}).items() -%}
        {%- for acc in accounts -%}
          <tr class="account-row">
            <td class="desc">• {{ acc.name }}</td>
            {%- for col in columns -%}
              <td class="num">{% if col == currency %}{{ acc.fmt }}{% else %}—{% endif %}</td>
            {%- endfor -%}
          </tr>
        {%- endfor -%}
      {%- endfor -%}
    {%- endif -%}
  {%- endmacro %}
  <section class="statement-title">
    <div class="eyebrow">Statement of Financial Position as of</div>
    <div class="period">{{ period_end }}</div>
  </section>
  <table class="income-table">
    <thead>
      <tr>
        <th class="desc"></th>
        {% for col in column_keys %}
        <th class="num">{{ column_labels[col] }}</th>
        {% endfor %}
      </tr>
    </thead>
    <tbody>
      {% for section in sections %}
      <tr class="section-row"><td class="desc">{{ section.title }}</td><td colspan="{{ column_keys|length }}"></td></tr>
      {% for row in section.rows %}
      <tr class="line-item">
        <td class="desc">{{ row.name }}</td>
        {% for col in column_keys %}
        <td class="num">{{ amount_cell(row, col) }}</td>
        {% endfor %}
      </tr>
      {{ account_rows(row, column_keys, show_accounts) | safe }}
      {% endfor %}
      <tr class="subtotal-row">
        <td class="desc">{{ section.total_label }}</td>
        {% for col in column_keys %}
        <td class="num">{{ total_cell(section.key, col) }}</td>
        {% endfor %}
      </tr>
      {% endfor %}
      <tr class="net-row">
        <td class="desc">Total Liabilities and Equity</td>
        {% for col in column_keys %}
        <td class="num">{{ total_cell('le', col) }}</td>
        {% endfor %}
      </tr>
    </tbody>
  </table>
</main>
<footer class="page-footer"><div class="footer-wrap"><div>Generated: {{ generated_at }}</div><div>Page <span class="page-number"></span> of <span class="total-pages"></span></div></div></footer>
</body></html>
"""

CF_TEMPLATE = r"""
<!DOCTYPE html><html><head><meta charset="utf-8"><title>{{ org }} — Cash Flow ({{ period }})</title>
<style>{{ base_css }}</style></head><body>
<header class="page-header"><div class="header-wrap"><div><div class="h-title">{{ org }}</div><div class="h-sub">Cash Flow Statement — {{ period }}</div><div class="h-sub" style="margin-top:4px;opacity:.8;">Prepared by Khairul Ammar Hakimi | 한태양 • {{ generated_at }}</div></div>{% if logo %}<img class="logo" src="{{ logo }}"/>{% endif %}</div></header>
<main class="statement-body">
  {% set show_accounts = column_keys|length == 1 and column_keys[0] != '__BASE__' %}

  {% macro total_cell(section_key, column) -%}
    {%- if column == '__BASE__' -%}
      {{ totals.get(section_key ~ '_fmt') or '—' }}
    {%- else -%}
      {%- set entry = currency_totals_map.get(column) -%}
      {{ entry.get(section_key ~ '_fmt') if entry else '—' }}
    {%- endif -%}
  {%- endmacro %}

  {% macro account_rows(row, columns, enabled) -%}
    {%- if enabled -%}
      {%- for currency, accounts in (row.account_details or {}).items() -%}
        {%- for acc in accounts -%}
          <tr class="account-row">
            <td class="desc">• {{ acc.name }}</td>
            {%- for col in columns -%}
              <td class="num">{% if col == currency %}{{ acc.fmt }}{% else %}—{% endif %}</td>
            {%- endfor -%}
          </tr>
        {%- endfor -%}
      {%- endfor -%}
    {%- endif -%}
  {%- endmacro %}

  <section class="statement-title">
    <div class="eyebrow">Cash Flow Statement as of</div>
    <div class="period">{{ end_date }}</div>
  </section>

  <div class="income-summary-grid">
    <div class="income-summary-card">
      <div class="metric-label">Opening Cash</div>
      <div class="metric-value">{{ totals.opening_fmt }}</div>
    </div>
    <div class="income-summary-card">
      <div class="metric-label">Closing Cash</div>
      <div class="metric-value">{{ totals.closing_fmt }}</div>
    </div>
    <div class="income-summary-card net">
      <div class="metric-label">Net Cash Change</div>
      <div class="metric-value">{{ totals.change_fmt }}</div>
    </div>
  </div>

  <table class="income-table">
    <thead>
      <tr>
        <th class="desc"></th>
        {% for col in column_keys %}
        <th class="num">{{ column_labels[col] }}</th>
        {% endfor %}
      </tr>
    </thead>
    <tbody>
      {% for section in sections %}
      <tr class="section-row"><td class="desc">{{ section.title }}</td><td colspan="{{ column_keys|length }}"></td></tr>
      {% for row in section.rows %}
      <tr class="line-item">
        <td class="desc">{{ row.name }}</td>
        {% for col in column_keys %}
        <td class="num">{{ row.amounts.get(col, '—') }}</td>
        {% endfor %}
      </tr>
      {{ account_rows(row, column_keys, show_accounts) | safe }}
      {% endfor %}
      <tr class="subtotal-row">
        <td class="desc">{{ section.total_label }}</td>
        {% for col in column_keys %}
        <td class="num">{{ total_cell(section.key, col) }}</td>
        {% endfor %}
      </tr>
      {% endfor %}
      <tr class="net-row">
        <td class="desc">Net Cash Flow</td>
        {% for col in column_keys %}
        <td class="num">{{ total_cell('net', col) }}</td>
        {% endfor %}
      </tr>
      <tr class="subtotal-row">
        <td class="desc">Opening Cash</td>
        {% for col in column_keys %}
        <td class="num">{{ total_cell('opening', col) }}</td>
        {% endfor %}
      </tr>
      <tr class="subtotal-row">
        <td class="desc">Closing Cash</td>
        {% for col in column_keys %}
        <td class="num">{{ total_cell('closing', col) }}</td>
        {% endfor %}
      </tr>
    </tbody>
  </table>
</main>
<footer class="page-footer"><div class="footer-wrap"><div>Generated: {{ generated_at }}</div><div>Page <span class="page-number"></span> of <span class="total-pages"></span></div></div></footer>
</body></html>
"""


DECIMAL_CURRENCIES = {'MYR', 'CNY'}


def _fmt(n: float) -> str:
    try:
        return f"₩ {n:,.0f}" if abs(n) >= 1 else f"₩ {n:,.2f}"
    except Exception:
        return "₩ 0"


def _fmt_ccy(n: float, currency: str) -> str:
    code = (currency or 'KRW').upper()
    try:
        if code in DECIMAL_CURRENCIES:
            text = f"{n:,.2f}"
            if '.' in text:
                text = text.rstrip('0').rstrip('.')
            return f"{code} {text}"
        return f"{code} {n:,.0f}" if abs(n) >= 1 else f"{code} {n:,.2f}"
    except Exception:
        return f"{code} 0"


def _coerce_date(value):
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str):
        try:
            return _dt.date.fromisoformat(value)
        except Exception:
            pass
    return _dt.date.today()


def _convert_amount_to_krw(amount: float, currency: str, on_date: _dt.date) -> float:
    cur = (currency or 'KRW').upper()
    if cur == 'KRW':
        return float(amount)
    rate = get_rate_to_krw(cur, on_date)
    try:
        return float(Decimal(str(amount)) * Decimal(str(rate)))
    except Exception:
        return float(amount) * float(rate)


def render_html(template: str, context: Dict[str, Any]) -> str:
    env = Environment(loader=BaseLoader(), autoescape=select_autoescape())
    tmpl = env.from_string(template)
    return tmpl.render(**context)


def build_income_statement_data(monthly: Dict[str, Any], statement_date: str | _dt.date | None = None) -> Dict[str, Any]:
    fx_date = _coerce_date(statement_date)
    rows: List[Dict[str, Any]] = []
    rev_total = 0.0
    exp_total = 0.0
    currency_breakdown: Dict[str, Dict[str, float]] = defaultdict(lambda: {'revenue': 0.0, 'expense': 0.0})
    currency_columns: Set[str] = set()
    row_currency_maps: List[Dict[str, float]] = []
    applied_rates: Dict[str, float] = {}

    def _convert(amount: float, currency: str) -> float:
        cur_code = (currency or 'KRW').upper()
        if cur_code == 'KRW':
            return float(amount)
        rate = applied_rates.get(cur_code)
        if rate is None:
            rate = get_rate_to_krw(cur_code, fx_date)
            applied_rates[cur_code] = rate
        quantized = Decimal(str(amount))
        return float(quantized * Decimal(str(rate)))

    for item in (monthly.get('groups', {}).get('income') or []):
        row_currency: Dict[str, float] = defaultdict(float)
        row_accounts: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        converted_row_total = 0.0
        for acc in (item.get('accounts') or []):
            cur = (acc.get('currency') or 'KRW').upper()
            a_amt = float(acc.get('period_credit') or 0.0) - float(acc.get('period_debit') or 0.0)
            row_currency[cur] += a_amt
            currency_breakdown[cur]['revenue'] += a_amt
            currency_columns.add(cur)
            converted_row_total += _convert(a_amt, cur)
            if abs(a_amt) > 0:
                row_accounts[cur].append({
                    'name': acc.get('name') or acc.get('category_name') or '',
                    'amount': a_amt,
                    'fmt': _fmt_ccy(a_amt, cur),
                })
        row_currency_maps.append(row_currency)
        rev_total += converted_row_total
        rows.append({
            'cat': 'Revenue',
            'name': item.get('category_name') or item.get('name') or '',
            'amt': converted_row_total,
            'amount': converted_row_total,
            'amt_fmt': _fmt(converted_row_total),
            'account_details': row_accounts,
        })
    for item in (monthly.get('groups', {}).get('expense') or []):
        row_currency: Dict[str, float] = defaultdict(float)
        row_accounts: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        converted_row_total = 0.0
        for acc in (item.get('accounts') or []):
            cur = (acc.get('currency') or 'KRW').upper()
            a_amt = float(acc.get('period_debit') or 0.0) - float(acc.get('period_credit') or 0.0)
            row_currency[cur] += a_amt
            currency_breakdown[cur]['expense'] += a_amt
            currency_columns.add(cur)
            converted_row_total += _convert(a_amt, cur)
            if abs(a_amt) > 0:
                row_accounts[cur].append({
                    'name': acc.get('name') or acc.get('category_name') or '',
                    'amount': a_amt,
                    'fmt': _fmt_ccy(a_amt, cur),
                })
        row_currency_maps.append(row_currency)
        exp_total += converted_row_total
        rows.append({
            'cat': 'Expense',
            'name': item.get('category_name') or item.get('name') or '',
            'amt': converted_row_total,
            'amount': converted_row_total,
            'amt_fmt': _fmt(converted_row_total),
            'account_details': row_accounts,
        })
    net_income = rev_total - exp_total
    totals = {
        'revenue': rev_total,
        'revenue_fmt': _fmt(rev_total),
        'expense': exp_total,
        'expense_fmt': _fmt(exp_total),
        'net_income': net_income,
        'net_income_fmt': _fmt(net_income),
    }
    currency_cols_sorted = sorted(currency_columns)
    for idx, row in enumerate(rows):
        cur_map = {}
        currency_amounts = row_currency_maps[idx] if idx < len(row_currency_maps) else {}
        for cur in currency_cols_sorted:
            val = float(currency_amounts.get(cur, 0.0))
            cur_map[cur] = {'amount': val, 'fmt': _fmt_ccy(val, cur)}
        row['currencies'] = cur_map
    currency_totals: List[Dict[str, Any]] = []
    for cur in sorted(currency_breakdown.keys()):
        rev = currency_breakdown[cur]['revenue']
        exp = currency_breakdown[cur]['expense']
        net = rev - exp
        currency_totals.append({
            'currency': cur,
            'revenue': rev,
            'revenue_fmt': _fmt_ccy(rev, cur),
            'expense': exp,
            'expense_fmt': _fmt_ccy(exp, cur),
            'net_income': net,
            'net_income_fmt': _fmt_ccy(net, cur),
        })
    return {
        'rows': rows,
        'totals': totals,
        'currency_totals': currency_totals,
        'currency_columns': currency_cols_sorted,
        'conversion': {
            'base_currency': 'KRW',
            'rate_date': fx_date.isoformat(),
            'rates': applied_rates,
        },
    }


def _income_statement_context_from_data(
    data: Dict[str, Any],
    org: str,
    start_date: str,
    end_date: str,
    logo: str | None = None,
) -> Dict[str, Any]:
    income_rows = [row for row in data['rows'] if (row.get('cat') or '').lower() == 'revenue']
    expense_rows = [row for row in data['rows'] if (row.get('cat') or '').lower() == 'expense']
    column_keys = list(data['currency_columns']) if data.get('currency_columns') else []
    if not column_keys:
        column_keys = ['__BASE__']
    column_labels = {key: ('Amount' if key == '__BASE__' else key) for key in column_keys}
    currency_totals_map = {entry['currency']: entry for entry in data.get('currency_totals', [])}
    ctx = {
        'org': org,
        'period': f"{start_date} to {end_date}",
        'start_date': start_date,
        'end_date': end_date,
        'generated_at': _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'rows': data['rows'],
        'income_rows': income_rows,
        'expense_rows': expense_rows,
        'totals': data['totals'],
        'currency_totals': data['currency_totals'],
        'currency_totals_map': currency_totals_map,
        'column_keys': column_keys,
        'column_labels': column_labels,
        'logo': logo,
        'base_css': BASE_CSS,
    }
    return ctx


def render_income_statement_html_from_data(
    data: Dict[str, Any],
    org: str,
    start_date: str,
    end_date: str,
    logo: str | None = None,
) -> str:
    return render_html(IS_TEMPLATE, _income_statement_context_from_data(data, org, start_date, end_date, logo=logo))


def generate_income_statement_pdf_from_data(
    data: Dict[str, Any],
    org: str,
    start_date: str,
    end_date: str,
    out_pdf: Path,
    logo: str | None = None,
) -> None:
    html = render_income_statement_html_from_data(data, org, start_date, end_date, logo=logo)
    render_with_weasyprint(html, out_pdf)


def generate_income_statement_pdf(monthly: Dict[str, Any], org: str, start_date: str, end_date: str, out_pdf: Path, logo: str | None = None) -> None:
    data = build_income_statement_data(monthly, end_date)
    generate_income_statement_pdf_from_data(data, org, start_date, end_date, out_pdf, logo=logo)


def build_balance_sheet_data(monthly: Dict[str, Any], statement_date: str | _dt.date | None = None) -> Dict[str, Any]:
    fx_date = _coerce_date(statement_date)
    groups = monthly.get('groups') or {}
    section_order = [('asset', 'Assets'), ('liability', 'Liabilities'), ('equity', 'Equity')]
    sections: List[Dict[str, Any]] = []
    currency_columns: Set[str] = set()
    currency_breakdown: Dict[str, Dict[str, float]] = defaultdict(lambda: {'assets': 0.0, 'liabilities': 0.0, 'equity': 0.0})
    totals_tracker = {'asset': 0.0, 'liability': 0.0, 'equity': 0.0}

    def _acc_amount(group_key: str, value: float) -> float:
        if group_key == 'asset':
            return value
        return abs(value)

    for key, label in section_order:
        section_rows: List[Dict[str, Any]] = []
        for item in (groups.get(key) or []):
            bal = float(item.get('balance') or 0.0)
            amt = _acc_amount(key, bal)
            totals_tracker[key] += amt
            row_currency: Dict[str, float] = defaultdict(float)
            account_details: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for acc in (item.get('accounts') or []):
                cur = (acc.get('currency') or 'KRW').upper()
                currency_columns.add(cur)
                acc_val = _acc_amount(key, float(acc.get('balance') or 0.0))
                row_currency[cur] += acc_val
                if abs(acc_val) > 0:
                    account_details[cur].append({
                        'name': acc.get('name') or acc.get('category_name') or '',
                        'amount': acc_val,
                        'fmt': _fmt_ccy(acc_val, cur),
                    })
                field = 'assets' if key == 'asset' else ('liabilities' if key == 'liability' else 'equity')
                currency_breakdown[cur][field] += acc_val
            row_currency_map = {cur: {'amount': amt_val, 'fmt': _fmt_ccy(amt_val, cur)} for cur, amt_val in row_currency.items()}
            sections_row = {
                'group': label,
                'key': key,
                'name': item.get('category_name') or item.get('name') or '',
                'amt': amt,
                'amt_fmt': _fmt(amt),
                'currencies': row_currency_map,
                'account_details': {cur: details for cur, details in account_details.items()},
            }
            section_rows.append(sections_row)
        sections.append({
            'key': key,
            'title': label,
            'rows': section_rows,
            'total_label': f"Total {label}",
        })
    currency_totals: List[Dict[str, Any]] = []
    for cur in sorted(currency_breakdown.keys()):
        assets_cur = currency_breakdown[cur]['assets']
        liabilities_cur = currency_breakdown[cur]['liabilities']
        equity_cur = assets_cur - liabilities_cur
        le_sum_cur = liabilities_cur + equity_cur
        currency_totals.append({
            'currency': cur,
            'assets': assets_cur,
            'assets_fmt': _fmt_ccy(assets_cur, cur),
            'liabilities': liabilities_cur,
            'liabilities_fmt': _fmt_ccy(liabilities_cur, cur),
            'equity': equity_cur,
            'equity_fmt': _fmt_ccy(equity_cur, cur),
            'le_sum': le_sum_cur,
            'le_sum_fmt': _fmt_ccy(le_sum_cur, cur),
        })
    assets_total = sum(_convert_amount_to_krw(entry['assets'], entry['currency'], fx_date) for entry in currency_totals)
    liabilities_total = sum(_convert_amount_to_krw(entry['liabilities'], entry['currency'], fx_date) for entry in currency_totals)
    equity_total = assets_total - liabilities_total
    totals = {
        'assets': assets_total,
        'assets_fmt': _fmt(assets_total),
        'liabilities': liabilities_total,
        'liabilities_fmt': _fmt(liabilities_total),
        'equity': equity_total,
        'equity_fmt': _fmt(equity_total),
        'le_sum': liabilities_total + equity_total,
        'le_sum_fmt': _fmt(liabilities_total + equity_total),
    }
    currency_columns_sorted = sorted(currency_columns)
    flat_rows = []
    for section in sections:
        flat_rows.extend(section['rows'])
    return {
        'rows': flat_rows,
        'sections': sections,
        'totals': totals,
        'currency_totals': currency_totals,
        'currency_columns': currency_columns_sorted,
    }


def _balance_sheet_context_from_data(
    data: Dict[str, Any],
    org: str,
    end_date: str,
    logo: str | None = None,
) -> Dict[str, Any]:
    column_keys = list(data.get('currency_columns') or [])
    if not column_keys:
        column_keys = ['__BASE__']
    column_labels = {key: ('Amount' if key == '__BASE__' else key) for key in column_keys}
    currency_totals_map = {entry['currency']: entry for entry in data.get('currency_totals', [])}
    ctx = {
        'org': org,
        'period': f"As of {end_date}",
        'period_end': end_date,
        'generated_at': _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'sections': data.get('sections') or [],
        'totals': data['totals'],
        'currency_totals': data['currency_totals'],
        'currency_totals_map': currency_totals_map,
        'column_keys': column_keys,
        'column_labels': column_labels,
        'logo': logo,
        'base_css': BASE_CSS,
    }
    return ctx


def render_balance_sheet_html_from_data(
    data: Dict[str, Any],
    org: str,
    end_date: str,
    logo: str | None = None,
) -> str:
    return render_html(BS_TEMPLATE, _balance_sheet_context_from_data(data, org, end_date, logo=logo))


def generate_balance_sheet_pdf_from_data(
    data: Dict[str, Any],
    org: str,
    end_date: str,
    out_pdf: Path,
    logo: str | None = None,
) -> None:
    html = render_balance_sheet_html_from_data(data, org, end_date, logo=logo)
    render_with_weasyprint(html, out_pdf)


def generate_balance_sheet_pdf(monthly: Dict[str, Any], org: str, end_date: str, out_pdf: Path, logo: str | None = None) -> None:
    data = build_balance_sheet_data(monthly, end_date)
    generate_balance_sheet_pdf_from_data(data, org, end_date, out_pdf, logo=logo)


def build_cashflow_statement_data(
    monthly: Dict[str, Any],
    cash_folder_ids: Sequence[int] | None = None,
    folder_lookup: Dict[int, str] | None = None,
    statement_date: str | _dt.date | None = None,
) -> Dict[str, Any]:
    fx_date = _coerce_date(statement_date)
    # Treat asset folders as cash when explicitly selected, otherwise rely on heuristics.
    folder_ids = {int(fid) for fid in (cash_folder_ids or []) if isinstance(fid, (int, float)) or str(fid).isdigit()}
    keywords = ('cash', 'bank', 'checking', 'savings')

    def _is_cash_folder(item: Dict[str, Any]) -> bool:
        cid = item.get('category_id')
        name = (item.get('category_name') or item.get('name') or '').strip().lower()
        if folder_ids:
            if cid is None:
                return False
            try:
                return int(cid) in folder_ids
            except Exception:
                return False
        return any(word in name for word in keywords)

    opening = closing = change = 0.0
    currency_breakdown: Dict[str, Dict[str, float]] = defaultdict(lambda: {'opening': 0.0, 'closing': 0.0})
    applied_ids: set[int] = set()
    for item in (monthly.get('groups', {}).get('asset') or []):
        if not _is_cash_folder(item):
            continue
        try:
            if item.get('category_id') is not None:
                applied_ids.add(int(item.get('category_id')))
        except Exception:
            pass
        opening += float(item.get('bd') or 0.0)
        closing += float(item.get('balance') or 0.0)
        for acc in (item.get('accounts') or []):
            cur = (acc.get('currency') or 'KRW').upper()
            currency_breakdown[cur]['opening'] += float(acc.get('bd') or 0.0)
            currency_breakdown[cur]['closing'] += float(acc.get('balance') or 0.0)
    change = closing - opening
    currency_totals: List[Dict[str, Any]] = []
    for cur in sorted(currency_breakdown.keys()):
        opening_cur = currency_breakdown[cur]['opening']
        closing_cur = currency_breakdown[cur]['closing']
        change_cur = closing_cur - opening_cur
        currency_totals.append({
            'currency': cur,
            'opening': opening_cur,
            'opening_fmt': _fmt_ccy(opening_cur, cur),
            'closing': closing_cur,
            'closing_fmt': _fmt_ccy(closing_cur, cur),
            'change': change_cur,
            'change_fmt': _fmt_ccy(change_cur, cur),
        })
    if currency_totals:
        opening = sum(_convert_amount_to_krw(entry['opening'], entry['currency'], fx_date) for entry in currency_totals)
        closing = sum(_convert_amount_to_krw(entry['closing'], entry['currency'], fx_date) for entry in currency_totals)
        change = closing - opening
    income_data = build_income_statement_data(monthly, statement_date)
    income_totals = income_data.get('totals') or {}
    income_currency_map = {entry['currency']: entry for entry in (income_data.get('currency_totals') or [])}
    currency_set = {entry['currency'] for entry in currency_totals} | set(income_currency_map.keys())
    currency_totals_map = {entry['currency']: entry for entry in currency_totals}
    driver_specs = [
        {'label': 'Changes in Accounts Receivable', 'group': 'asset', 'keywords': ('account receivable', 'accounts receivable', 'receivable')},
        {'label': 'Changes in Prepaid Expenses', 'group': 'asset', 'keywords': ('prepaid',)},
        {'label': 'Changes in Short Term Debt', 'group': 'liability', 'keywords': ('short term debt', 'short-term debt', 'short term loan')},
    ]

    def _acc_amount_for_group(group_key: str, value: float) -> float:
        return value if group_key == 'asset' else abs(value)

    def _compute_change(item: Dict[str, Any], group_key: str) -> Tuple[float, Dict[str, float]]:
        opening_val = _acc_amount_for_group(group_key, float(item.get('bd') or 0.0))
        closing_val = _acc_amount_for_group(group_key, float(item.get('balance') or 0.0))
        change_amt = closing_val - opening_val
        currency_map: Dict[str, float] = defaultdict(float)
        for acc in (item.get('accounts') or []):
            cur = (acc.get('currency') or 'KRW').upper()
            open_acc = _acc_amount_for_group(group_key, float(acc.get('bd') or 0.0))
            close_acc = _acc_amount_for_group(group_key, float(acc.get('balance') or 0.0))
            currency_map[cur] += close_acc - open_acc
        return change_amt, dict(currency_map)

    driver_rows_data: List[Dict[str, Any]] = []

    def _matches(name: str, keywords: Tuple[str, ...]) -> bool:
        lowered = (name or '').strip().lower()
        return any(token in lowered for token in keywords)

    for spec in driver_specs:
        for item in (monthly.get('groups', {}).get(spec['group']) or []):
            cat_name = item.get('category_name') or item.get('name') or ''
            if _matches(cat_name, spec['keywords']):
                change_amt, currency_map = _compute_change(item, spec['group'])
                driver_rows_data.append({
                    'label': spec['label'],
                    'change': change_amt,
                    'currency_map': currency_map,
                })
                currency_set.update(currency_map.keys())
                break

    currency_columns_sorted = sorted(currency_set)
    for cur in currency_columns_sorted:
        if cur not in currency_totals_map:
            zero_entry = {
                'currency': cur,
                'opening': 0.0,
                'opening_fmt': _fmt_ccy(0.0, cur),
                'closing': 0.0,
                'closing_fmt': _fmt_ccy(0.0, cur),
                'change': 0.0,
                'change_fmt': _fmt_ccy(0.0, cur),
            }
            currency_totals.append(zero_entry)
            currency_totals_map[cur] = zero_entry
    for entry in currency_totals:
        cur = entry['currency']
        entry['operating_fmt'] = entry['change_fmt']
        entry['investing_fmt'] = _fmt_ccy(0.0, cur)
        entry['financing_fmt'] = _fmt_ccy(0.0, cur)
        entry['net_fmt'] = entry['change_fmt']

    def _amount_map(base_value: float, per_currency_values: Dict[str, float]) -> Dict[str, str]:
        amounts = {'__BASE__': _fmt(base_value)}
        for cur in currency_columns_sorted:
            val = per_currency_values.get(cur, 0.0)
            amounts[cur] = _fmt_ccy(val, cur)
        return amounts

    net_income_base = float(income_totals.get('net_income') or 0.0)
    net_income_currency_values = {cur: entry.get('net_income', 0.0) for cur, entry in income_currency_map.items()}
    net_income_amounts = _amount_map(net_income_base, net_income_currency_values)

    operating_rows = [
        {'name': 'Net Income', 'amounts': net_income_amounts, 'account_details': {}},
    ]
    driver_map = {driver['label']: driver for driver in driver_rows_data}

    def _driver_effect(label: str, sign: float) -> Tuple[float, Dict[str, float]]:
        driver = driver_map.get(label)
        base_change = (driver.get('change') if driver else 0.0) * sign
        currency_vals: Dict[str, float] = {}
        if driver:
            for cur, amount in driver.get('currency_map', {}).items():
                currency_vals[cur] = amount * sign
        return base_change, currency_vals

    ar_base, ar_currency = _driver_effect('Changes in Accounts Receivable', -1.0)
    prepaid_base, prepaid_currency = _driver_effect('Changes in Prepaid Expenses', -1.0)
    debt_base, debt_currency = _driver_effect('Changes in Short Term Debt', 1.0)

    operating_rows.extend([
        {'name': 'Changes in Accounts Receivable', 'amounts': _amount_map(ar_base, ar_currency), 'account_details': {}},
        {'name': 'Changes in Prepaid Expenses', 'amounts': _amount_map(prepaid_base, prepaid_currency), 'account_details': {}},
        {'name': 'Changes in Short Term Debt', 'amounts': _amount_map(debt_base, debt_currency), 'account_details': {}},
    ])

    operating_total_base = net_income_base + ar_base + prepaid_base + debt_base
    operating_currency_values: Dict[str, float] = {}
    for cur in currency_columns_sorted:
        operating_currency_values[cur] = (
            net_income_currency_values.get(cur, 0.0)
            + ar_currency.get(cur, 0.0)
            + prepaid_currency.get(cur, 0.0)
            + debt_currency.get(cur, 0.0)
        )
    for entry in currency_totals:
        cur = entry['currency']
        entry['operating_fmt'] = _fmt_ccy(operating_currency_values.get(cur, 0.0), cur)

    sections = [
        {
            'key': 'operating',
            'title': 'Operating Activities',
            'rows': operating_rows,
            'total_label': 'Net Cash from Operating Activities',
        },
        {
            'key': 'investing',
            'title': 'Investing Activities',
            'rows': [],
            'total_label': 'Net Cash from Investing Activities',
        },
        {
            'key': 'financing',
            'title': 'Financing Activities',
            'rows': [],
            'total_label': 'Net Cash from Financing Activities',
        },
    ]
    totals = {
        'opening': opening,
        'opening_fmt': _fmt(opening),
        'closing': closing,
        'closing_fmt': _fmt(closing),
        'change': change,
        'change_fmt': _fmt(change),
        'operating': operating_total_base,
        'operating_fmt': _fmt(operating_total_base),
        'investing': 0.0,
        'investing_fmt': _fmt(0.0),
        'financing': 0.0,
        'financing_fmt': _fmt(0.0),
        'net': change,
        'net_fmt': _fmt(change),
    }
    return {
        'opening': opening,
        'opening_fmt': _fmt(opening),
        'closing': closing,
        'closing_fmt': _fmt(closing),
        'change': change,
        'change_fmt': _fmt(change),
        'currency_totals': currency_totals,
        'sections': sections,
        'totals': totals,
        'currency_columns': currency_columns_sorted,
        'applied_folder_ids': sorted(list(applied_ids)),
        'applied_folder_names': [
            (folder_lookup.get(fid) if folder_lookup else '') for fid in sorted(list(applied_ids))
        ] if applied_ids else [],
    }


def generate_cashflow_pdf(
    monthly: Dict[str, Any],
    org: str,
    start_date: str,
    end_date: str,
    out_pdf: Path,
    logo: str | None = None,
    cash_folder_ids: Sequence[int] | None = None,
) -> None:
    data = build_cashflow_statement_data(monthly, cash_folder_ids=cash_folder_ids, statement_date=end_date)
    generate_cashflow_pdf_from_data(data, org, start_date, end_date, out_pdf, logo=logo)


def _cashflow_context_from_data(
    data: Dict[str, Any],
    org: str,
    start_date: str,
    end_date: str,
    logo: str | None = None,
) -> Dict[str, Any]:
    column_keys = list(data.get('currency_columns') or [])
    if not column_keys:
        column_keys = ['__BASE__']
    column_labels = {key: ('Amount' if key == '__BASE__' else key) for key in column_keys}
    currency_totals_map = {entry['currency']: entry for entry in data.get('currency_totals', [])}
    ctx = {
        'org': org,
        'period': f"{start_date} to {end_date}",
        'end_date': end_date,
        'generated_at': _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'sections': data.get('sections') or [],
        'totals': data.get('totals') or {},
        'currency_totals': data.get('currency_totals') or [],
        'currency_totals_map': currency_totals_map,
        'column_keys': column_keys,
        'column_labels': column_labels,
        'logo': logo,
        'base_css': BASE_CSS,
    }
    return ctx


def render_cashflow_html_from_data(
    data: Dict[str, Any],
    org: str,
    start_date: str,
    end_date: str,
    logo: str | None = None,
) -> str:
    return render_html(CF_TEMPLATE, _cashflow_context_from_data(data, org, start_date, end_date, logo=logo))


def generate_cashflow_pdf_from_data(
    data: Dict[str, Any],
    org: str,
    start_date: str,
    end_date: str,
    out_pdf: Path,
    logo: str | None = None,
) -> None:
    html = render_cashflow_html_from_data(data, org, start_date, end_date, logo=logo)
    render_with_weasyprint(html, out_pdf)
