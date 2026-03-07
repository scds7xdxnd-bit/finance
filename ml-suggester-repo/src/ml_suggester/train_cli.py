from __future__ import annotations

import json
from pathlib import Path

import click
import joblib
import pandas as pd

from .features import feature_target_split, prepare_dataframe
from .models import train_eval_pipeline


@click.group()
def traincli():
    """Training & inference commands."""
    pass

@traincli.command("train")
@click.option("--input", "input_path", required=True, type=click.Path(exists=True), help="lines.parquet or .csv from transformer")
@click.option("--outdir", required=True, type=str, help="Directory to save model artifacts")
@click.option("--format", "fmt", default=None, type=click.Choice(["parquet","csv"]), help="If not given, inferred from extension")
@click.option("--min-class-count", default=2, show_default=True, type=int, help="Drop labels with fewer than this many rows before splitting")
@click.option("--currency", default="", type=str, help="Optional: train on a single currency, e.g. 'KRW'")
@click.option("--other-threshold", default=2, show_default=True, type=int, help="Map accounts with fewer than this many rows to '__OTHER__'")

def train(input_path, outdir, fmt, min_class_count, currency, other_threshold):
    out = Path(outdir); out.mkdir(parents=True, exist_ok=True)
    if fmt is None:
        fmt = "parquet" if input_path.endswith(".parquet") else "csv"
    df = pd.read_parquet(input_path) if fmt == "parquet" else pd.read_csv(input_path)

    df = prepare_dataframe(df)
    if currency:
        df = df[df["Currency"].str.upper() == currency.upper()].reset_index(drop=True)
    # Map rares to OTHER
    vc = df["Account_Name"].value_counts()
    rare = set(vc[vc < other_threshold].index)
    df.loc[df["Account_Name"].isin(rare), "Account_Name"] = "__OTHER__"

    X, y = feature_target_split(df)
    groups = df["Transaction_ID"]
    model, metrics = train_eval_pipeline(X, y, groups=groups, min_class_count=1) 

    joblib.dump(model, out / "model.joblib")
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (out / "schema.json").write_text(json.dumps({"feature_columns": list(X.columns)}, indent=2), encoding="utf-8")

    click.echo(f"Saved model to {out/'model.joblib'}")
    click.echo(f"Validation metrics: {metrics}")

@traincli.command("predict")
@click.option("--model", "model_path", required=True, type=click.Path(exists=True), help="Path to model.joblib")
@click.option("--input", "input_path", required=True, type=click.Path(exists=True), help="lines-like file to score (same columns as training)")
@click.option("--topk", default=3, type=int, show_default=True, help="How many suggestions to return")
@click.option("--out", "out_path", required=False, type=str, help="Where to write predictions (CSV). If omitted, prints head()")
def predict(model_path, input_path, topk, out_path):
    """Score lines and return top-k account suggestions."""
    import joblib
    import numpy as np
    import pandas as pd

    model = joblib.load(model_path)

    # Load data
    fmt = "parquet" if input_path.endswith(".parquet") else "csv"
    df = pd.read_parquet(input_path) if fmt == "parquet" else pd.read_csv(input_path)

    # Prepare features (label column not required)
    from .features import feature_target_split, prepare_dataframe
    df2 = prepare_dataframe(df.assign(Account_Name=df.get("Account_Name", "")))
    X, _ = feature_target_split(df2)

    # Predict probabilities (or decision_function fallback)
    try:
        proba = model.predict_proba(X)
    except Exception:
        df_scores = model.decision_function(X)
        exp = np.exp(df_scores - df_scores.max(axis=1, keepdims=True))
        proba = exp / exp.sum(axis=1, keepdims=True)

    # Figure out class labels
    classes = getattr(model, "_classes", None)
    if classes is None:
        # try estimator (e.g., LogisticRegression)
        classes = getattr(model.named_steps["clf"], "classes_", None)
    if classes is None:
        raise RuntimeError("Model classes not found on pipeline. Re-train with updated code.")

    # Top-k selection
    top_idx = np.argsort(-proba, axis=1)[:, :topk]
    top_labels = np.array(classes)[top_idx]
    top_scores = np.take_along_axis(proba, top_idx, axis=1)

    # Build output
    out_df = df.copy()
    for i in range(topk):
        out_df[f"pred_{i+1}_account"] = top_labels[:, i]
        out_df[f"pred_{i+1}_score"] = top_scores[:, i]

    if out_path:
        out_df.to_csv(out_path, index=False)
        click.echo(f"Wrote predictions -> {out_path}")
    else:
        click.echo(out_df.head(min(10, len(out_df))).to_string(index=False))

if __name__ == "__main__":
    traincli()
