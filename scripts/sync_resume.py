"""Export resume content, tracking all README bytes including whitespace."""

import hashlib
import json
import subprocess
import textwrap
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]


def marked_section(lines, start, end):
    starts = [
        index
        for index, line in enumerate(lines)
        if line.rstrip(b"\r\n") == start
    ]
    ends = [
        index
        for index, line in enumerate(lines)
        if line.rstrip(b"\r\n") == end
    ]
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise ValueError(
            f"Expected exactly one ordered pair of markers: "
            f"{start.decode()} / {end.decode()}"
        )
    return starts[0], ends[0]


def preserve_links(node):
    if isinstance(node, list):
        return [preserve_links(item) for item in node]
    if not isinstance(node, dict):
        return node

    if node.get("t") == "Link":
        attributes, label, target = node["c"]
        return {
            "t": "Span",
            "c": [
                attributes,
                preserve_links(label)
                + [
                    {"t": "Space"},
                    {"t": "Str", "c": f"({target[0]})"},
                ],
            ],
        }

    return {key: preserve_links(value) for key, value in node.items()}


def render_pdf(text, destination, source_digest):
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
    pdfmetrics.registerFont(TTFont("ResumeMono", font_path))

    width, height = letter
    margin = 42
    font_size = 9
    line_height = 12
    character_width = pdfmetrics.stringWidth("M", "ResumeMono", font_size)
    columns = int((width - 2 * margin) / character_width)

    pdf = canvas.Canvas(
        str(destination),
        pagesize=letter,
        invariant=1,
        pageCompression=1,
    )
    pdf.setTitle("Resume")
    pdf.setSubject(f"README SHA-256: {source_digest}")
    pdf.setFont("ResumeMono", font_size)
    y = height - margin

    for line in text.splitlines():
        line = line.expandtabs(4)
        indent = line[: len(line) - len(line.lstrip())]
        wrapped = textwrap.wrap(
            line,
            width=columns,
            subsequent_indent=indent,
            break_long_words=True,
            break_on_hyphens=False,
        ) or [""]

        for part in wrapped:
            if y < margin:
                pdf.showPage()
                pdf.setFont("ResumeMono", font_size)
                y = height - margin
            pdf.drawString(margin, y, part)
            y -= line_height

    pdf.save()


def main():
    readme_bytes = (ROOT / "README.md").read_bytes()
    source_digest = hashlib.sha256(readme_bytes).hexdigest()
    readme_lines = readme_bytes.splitlines(keepends=True)
    first, last = marked_section(
        readme_lines,
        b"<!-- resume:start -->",
        b"<!-- resume:end -->",
    )
    markdown = b"".join(readme_lines[first + 1:last]).decode("utf-8")
    if not markdown.strip():
        raise ValueError("The README resume section is empty.")

    parsed = subprocess.run(
        ["pandoc", "--from=gfm", "--to=json"],
        input=markdown,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    document = preserve_links(json.loads(parsed.stdout))
    converted = subprocess.run(
        ["pandoc", "--from=json", "--to=plain", "--wrap=none"],
        input=json.dumps(document),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    body = converted.stdout.strip()
    if not body:
        raise ValueError("The converted resume body is empty.")

    resume_path = ROOT / "RESUME.txt"
    resume_lines = resume_path.read_bytes().splitlines(keepends=True)
    first, last = marked_section(
        resume_lines,
        b"<!-- resume:body:start -->",
        b"<!-- resume:body:end -->",
    )
    start_line = resume_lines[first]
    if not start_line.endswith(b"\n"):
        raise ValueError("The body start marker must end with a newline.")

    newline = b"\r\n" if start_line.endswith(b"\r\n") else b"\n"
    body_bytes = body.replace("\r\n", "\n").encode("utf-8")
    body_bytes = body_bytes.replace(b"\n", newline) + newline

    prefix = b"".join(resume_lines[:first + 1])
    suffix = b"".join(resume_lines[last:])
    # Pandoc normalizes whitespace; track the exact source independently.
    source_marker = (
        f"<!-- resume:source:sha256 {source_digest} -->".encode("ascii")
        + newline
    )
    updated = prefix + source_marker + body_bytes + suffix

    # Export the updated text without displaying the control markers.
    printable = (
        b"".join(resume_lines[:first])
        + body_bytes
        + b"".join(resume_lines[last + 1:])
    )
    temporary_pdf = ROOT / "RESUME.pdf.tmp"
    try:
        render_pdf(printable.decode("utf-8"), temporary_pdf, source_digest)
        resume_path.write_bytes(updated)
        temporary_pdf.replace(ROOT / "RESUME.pdf")
    finally:
        temporary_pdf.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
