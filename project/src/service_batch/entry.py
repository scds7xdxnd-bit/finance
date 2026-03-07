"""CLI entrypoint for scheduled batch inference runs."""
from __future__ import annotations

import argparse
import json
import sys

from ..models.inference_batch import DataValidationError, run_batch_inference


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Batch inference service entrypoint")
    parser.add_argument("--in", dest="input_path", required=True, help="Input CSV/Parquet path")
    parser.add_argument("--out", dest="output_path", required=True, help="Output Parquet path")
    parser.add_argument(
        "--model",
        dest="model_selector",
        default="best",
        help="Model version to load (default: best)",
    )
    args = parser.parse_args(argv)

    try:
        summary = run_batch_inference(args.input_path, args.output_path, args.model_selector)
    except DataValidationError as exc:
        sys.stderr.write(json.dumps({"invalid_rows": exc.issues}, indent=2) + "\n")
        return 2
    except Exception as exc:
        sys.stderr.write(
            json.dumps(
                {
                    "status": "error",
                    "error_code": "BATCH_FAILURE",
                    "message": str(exc),
                    "input_path": args.input_path,
                },
                indent=2,
            )
            + "\n"
        )
        return 1

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
