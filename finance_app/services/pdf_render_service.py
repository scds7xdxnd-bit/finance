from __future__ import annotations

from pathlib import Path
from typing import Iterable

from flask import Response, render_template


def _escape_pdf_text(value: str) -> str:
    return (
        (value or "")
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def _build_minimal_pdf(lines: Iterable[str]) -> bytes:
    rendered_lines = [str(line).strip() for line in (lines or []) if str(line).strip()]
    if not rendered_lines:
        rendered_lines = ["Document"]

    content_rows = ["BT", "/F1 11 Tf", "50 790 Td"]
    for idx, line in enumerate(rendered_lines):
        if idx > 0:
            content_rows.append("0 -14 Td")
        content_rows.append(f"({_escape_pdf_text(line)}) Tj")
    content_rows.append("ET")
    stream = "\n".join(content_rows).encode("latin-1", errors="replace")

    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        b"5 0 obj << /Length " + str(len(stream)).encode("ascii") + b" >> stream\n" + stream + b"\nendstream endobj\n",
    ]
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(output))
        output.extend(obj)

    xref_pos = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer << /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n"
            "%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def render_template_pdf(
    *,
    template_name: str,
    context: dict,
    filename: str,
    fallback_lines: Iterable[str] | None = None,
) -> Response:
    html = render_template(template_name, **(context or {}))

    pdf_bytes: bytes
    try:
        from weasyprint import HTML

        pdf_bytes = HTML(string=html, base_url=str(Path.cwd())).write_pdf()
        if not isinstance(pdf_bytes, (bytes, bytearray)) or not bytes(pdf_bytes).startswith(b"%PDF"):
            raise RuntimeError("weasyprint returned non-pdf payload")
        pdf_bytes = bytes(pdf_bytes)
    except Exception:
        pdf_bytes = _build_minimal_pdf(fallback_lines or [])

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
