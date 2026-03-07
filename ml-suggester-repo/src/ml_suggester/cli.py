from __future__ import annotations

from pathlib import Path

import click

from .data_io import load_excel, write_table
from .parse_blocks import explode_to_lines, infer_transactions


@click.group()
def main():
    """ML Suggester Utilities"""
    pass

@main.command("transform")
@click.option("--input", "input_path", required=True, type=click.Path(exists=True), help="Excel file path")
@click.option("--sheet", "sheet_name", required=False, default=None, help="Sheet name or index (optional)")
@click.option("--out", "out_path", required=True, type=str, help="Output file (CSV or Parquet)")
@click.option("--out-format", "out_format", required=False, default="parquet", type=click.Choice(["parquet", "csv"]), help="Output format")
@click.option("--include-imbalanced", is_flag=True, default=False, help="If set, write imbalanced transactions alongside")
@click.option("--imbalanced-out", default=None, type=str, help="Optional path to write imbalanced transactions table")
@click.option("--currencies", default="", type=str,
              help="Comma-separated list to map numbered Debit/Credit columns to currencies, e.g. 'KRW,MYR,CNY'")
def transform(input_path, sheet_name, out_path, out_format, include_imbalanced, imbalanced_out, currencies):
    """Transform Excel ledger blocks into a long, multi-currency, line-level dataset."""
    click.echo(f"Loading Excel: {input_path}")
    cur_list = [c.strip().upper() for c in currencies.split(",")] if currencies else None
    df = load_excel(input_path, sheet_name=sheet_name, currencies=cur_list)

    click.echo("Inferring transactions...")
    blocks = infer_transactions(df)

    click.echo(f"Found {len(blocks)} transaction blocks. Exploding to lines by currency...")
    lines_df, imbalanced_df = explode_to_lines(blocks)

    click.echo(f"Writing lines -> {out_path} ({out_format})")
    write_table(lines_df, out_path, out_format)

    if include_imbalanced:
        out2 = imbalanced_out or _default_imbalanced_path(out_path, out_format)
        click.echo(f"Writing imbalanced transactions -> {out2}")
        write_table(imbalanced_df, out2, out_format)

    click.echo("Done.")

def _default_imbalanced_path(out_path: str, out_format: str) -> str:
    p = Path(out_path)
    stem = p.stem
    suffix = ".parquet" if out_format == "parquet" else ".csv"
    return str(p.with_name(f"{stem}.imbalanced{suffix}"))

from .train_cli import traincli

main.add_command(traincli, name="model")

if __name__ == "__main__":
    main()
