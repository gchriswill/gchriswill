"""Qualify the non-production Swift exporter against fresh Python outputs."""

import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import textwrap
import time
import xml.etree.ElementTree as ET
import zlib


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".qualification" / "outputs"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(args, capture_output=True, **kwargs)
    if result.returncode:
        raise RuntimeError(f"{args} failed ({result.returncode}): {result.stderr.decode(errors='replace')}")
    return result


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_baseline():
    spec = importlib.util.spec_from_file_location("baseline", ROOT / "scripts/sync_resume.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load Python baseline")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wrapping_oracle() -> None:
    rng = random.Random(20261013)
    cases = []
    samples = [
        "", "   ", "  alpha beta gamma", "a\tb", "a-b-c-d-e",
        "a\u0301bc", "A\u00a0B C", "\u00a0", "\u2003 abc", " " * 100 + "abcdef",
        "https://example.com/" + "x" * 160, "a  b    c", "a\v b\f c",
    ]
    samples += [
        "".join(rng.choice("abc -\t\u00a0\u2003\u0301") for _ in range(rng.randrange(150)))
        for _ in range(300)
    ]
    for text in samples:
        expanded = text.expandtabs(4)
        indent = expanded[:len(expanded) - len(expanded.lstrip())]
        for columns in [1, 2, 5, 10, 97]:
            expected = textwrap.wrap(
                expanded, width=columns, subsequent_indent=indent,
                break_long_words=True, break_on_hyphens=False,
            ) or [""]
            cases.append({"text": text, "columns": columns, "expected": expected})
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "wrapping.json").write_text(json.dumps(cases), encoding="utf-8")
    print(f"Created {len(cases)} Python wrapping oracle cases")


def fixture(directory: Path, readme: bytes, resume: bytes) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "README.md").write_bytes(readme)
    (directory / "RESUME.txt").write_bytes(resume)
    scripts = directory / "scripts"
    scripts.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "scripts/sync_resume.py", scripts / "sync_resume.py")


def python_layout(module, directory: Path) -> dict:
    text = (directory / "RESUME.txt").read_bytes()
    source = text.splitlines(keepends=True)
    first, last = module.marked_section(
        source, b"<!-- resume:body:start -->", b"<!-- resume:body:end -->"
    )
    printable = b"".join(
        source[:first] + source[first + 2:last] + source[last + 1:]
    ).decode("utf-8")
    advance = module.pdfmetrics.stringWidth("M", "ResumeMono", 9)
    columns = int(528 / advance)
    page, y = 1, 750
    result = []
    for line in printable.splitlines():
        line = line.expandtabs(4)
        indent = line[:len(line) - len(line.lstrip())]
        for part in textwrap.wrap(
            line, width=columns, subsequent_indent=indent,
            break_long_words=True, break_on_hyphens=False,
        ) or [""]:
            if y < 42:
                page, y = page + 1, 750
            result.append({"text": part, "page": page, "x": 42, "y": y})
            y -= 12
    return {"columns": columns, "characterWidth": advance, "lines": result}


def pdf_checks(python: Path, swift: Path, source_digest: str) -> dict:
    from PIL import Image, ImageChops

    info = {}
    words = {}
    extracted = {}
    for name, directory in [("python", python), ("swift", swift)]:
        pdf = directory / "RESUME.pdf"
        metadata = run(["pdfinfo", str(pdf)]).stdout.decode()
        info[name] = {
            key: value.strip()
            for key, value in re.findall(r"^([^:\n]+):[ \t]*(.*)$", metadata, re.M)
        }
        for key, expected in [
            ("Title", "Resume"), ("Subject", f"README SHA-256: {source_digest}"),
            ("Page size", "612 x 792 pts (letter)"),
        ]:
            if info[name].get(key) != expected:
                raise AssertionError(f"{name} metadata {key}: {info[name].get(key)}")
        fonts = run(["pdffonts", str(pdf)]).stdout.decode()
        if not any("DejaVuSansMono" in line and re.search(r"yes\s+yes\s+yes", line)
                   for line in fonts.splitlines()):
            raise AssertionError(f"{name}: missing embedded Unicode font: {fonts}")
        extracted[name] = run(["pdftotext", "-layout", str(pdf), "-"]).stdout
        if b"<!-- resume:" in extracted[name]:
            raise AssertionError("Control markers appeared in PDF")
        bbox = ET.fromstring(run(["pdftotext", "-bbox", str(pdf), "-"]).stdout)
        words[name] = [
            (node.text, float(node.attrib["xMin"]), float(node.attrib["yMin"]))
            for node in bbox.iter() if node.tag.endswith("}word")
        ]
        run(["pdftoppm", "-r", "72", "-gray", str(pdf), str(directory / "raster")])
        streams = []
        data = pdf.read_bytes()
        for match in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
            encoded = match[1].strip()
            header = data[data.rfind(b" obj", 0, match.start()):match.start()]
            if b"/ASCII85Decode" in header:
                encoded = base64.a85decode(encoded, adobe=True)
            if b"/FlateDecode" in header:
                encoded = zlib.decompress(encoded)
            if b" Tm" in encoded or b" Td" in encoded:
                streams.append(encoded)
        (directory / "drawing-streams.txt").write_bytes(b"\n\n".join(streams))
    if info["python"]["Pages"] != info["swift"]["Pages"]:
        raise AssertionError("PDF page counts differ")
    for date in ["CreationDate", "ModDate"]:
        if info["python"].get(date) != info["swift"].get(date):
            raise AssertionError(f"PDF invariant {date} differs")
    text_equal = extracted["python"] == extracted["swift"]
    same_words = [w[0] for w in words["python"]] == [w[0] for w in words["swift"]]
    max_x = max_y = None
    if same_words:
        max_x = max((abs(p[1] - s[1]) for p, s in zip(words["python"], words["swift"])), default=0)
        max_y = max((abs(p[2] - s[2]) for p, s in zip(words["python"], words["swift"])), default=0)
    pixels = []
    for p, s in zip(sorted(python.glob("raster-*.pgm")), sorted(swift.glob("raster-*.pgm"))):
        with Image.open(p) as a, Image.open(s) as b:
            delta = ImageChops.difference(a, b)
            pixels.append({
                "python_ink_bounds": a.point(lambda value: 255 if value < 128 else 0).getbbox(),
                "swift_ink_bounds": b.point(lambda value: 255 if value < 128 else 0).getbbox(),
                "changed_pixels": a.width * a.height - delta.histogram()[0],
            })
            if p == sorted(python.glob("raster-*.pgm"))[0]:
                preview = Image.new("L", (a.width * 3, a.height), 255)
                preview.paste(a, (0, 0))
                preview.paste(b, (a.width, 0))
                preview.paste(ImageChops.invert(delta), (a.width * 2, 0))
                preview.save(swift / "raster-comparison.png")
    return {
        "pages": int(info["swift"]["Pages"]), "layout_extraction_equal": text_equal,
        "words_equal": same_words, "maximum_word_x_delta": max_x, "maximum_word_y_delta": max_y,
        "producer": info["swift"].get("Producer"),
        "creation_date": info["swift"].get("CreationDate"),
        "modification_date": info["swift"].get("ModDate"),
        "raster_manual_review": "required",
        "raster_pages": pixels,
    }


def qualify(binary: Path) -> bool:
    module = load_baseline()
    module.pdfmetrics.registerFont(module.TTFont("ResumeMono", FONT))
    template = (
        b"Preamble\twith tab\n<!-- resume:body:start -->\nold body\n"
        b"<!-- resume:body:end -->\nSuffix without final newline"
    )
    markdown = """\n\n# Heading one

Paragraph with [**formatted** _label_](https://example.com/path) and Unicode: café — “Swift”.

## Heading two

- item with a long URL https://example.com/""" + "x" * 140 + """
  - nested item

### Heading three
```swift
# not a heading
let x = 1
```

#### Heading four
~~~
## still not a heading
~~~

##### Heading five
Line with\ttabs and a long token """ + "a" * 180 + """

###### Heading six

Final paragraph.
"""
    marked = "<!-- resume:start -->\n" + markdown + "<!-- resume:end -->\n"
    fixtures = {
        "actual": ((ROOT / "README.md").read_bytes(), (ROOT / "RESUME.txt").read_bytes()),
        "lf": (marked.encode(), template),
        "crlf": (marked.replace("\n", "\r\n").encode(), template.replace(b"\n", b"\r\n")),
        "outside-digest": (("Outside-only change\n" + marked).encode(), template),
        "unicode": (("<!-- resume:start -->\n# Unicode\n\nAliases: - −; combining: a\u0301; punctuation: … – ’.\n<!-- resume:end -->\n").encode(), template),
        "unicode-renderer": (
            b"<!-- resume:start -->\n# Unicode renderer\n\nBody.\n<!-- resume:end -->\n",
            ("Direct Unicode: a\u0301 A\u030a; aliases: - −; spacing: A\u00a0B; quotes: “Swift” … – ’.\n").encode()
            + template[template.index(b"<!-- resume:body:start -->"):],
        ),
        "pagination": (("<!-- resume:start -->\n# Pages\n\n```\n" + "line\n" * 130 + "```\n<!-- resume:end -->\n").encode(), template),
        "empty-printable-lines": (b"<!-- resume:start -->\nSimple paragraph.\n<!-- resume:end -->\n", template),
        "nested-heading": (b"<!-- resume:start -->\n> # Nested\n<!-- resume:end -->\n", template),
    }
    report = {"fixtures": {}, "failures": [], "runtime_seconds": {}}
    for name, (readme, resume) in fixtures.items():
        python = WORK / name / "python"
        swift = WORK / name / "swift"
        fixture(python, readme, resume)
        fixture(swift, readme, resume)
        started = time.monotonic()
        run([sys.executable, str(python / "scripts/sync_resume.py")])
        report["runtime_seconds"][f"{name}_python"] = time.monotonic() - started
        started = time.monotonic()
        run([str(binary), "--root", str(swift), "--layout", str(swift / "layout.json")], cwd=ROOT / "scripts")
        report["runtime_seconds"][f"{name}_swift"] = time.monotonic() - started
        if (python / "RESUME.txt").read_bytes() != (swift / "RESUME.txt").read_bytes():
            raise AssertionError(f"{name}: text bytes differ")
        oracle = python_layout(module, python)
        (python / "layout.json").write_text(json.dumps(oracle, indent=2), encoding="utf-8")
        actual = json.loads((swift / "layout.json").read_text())
        if (oracle["columns"] != actual["columns"] or oracle["lines"] != actual["lines"]
                or abs(oracle["characterWidth"] - actual["characterWidth"]) > 1e-10):
            raise AssertionError(
                f"{name}: wrapped lines or placement differ; "
                f"metrics: Python {oracle['characterWidth']}, Swift {actual['characterWidth']}; "
                f"lines: Python {len(oracle['lines'])}, Swift {len(actual['lines'])}"
            )
        hashes = [sha(swift / filename) for filename in ["RESUME.txt", "RESUME.pdf"]]
        run([str(binary), "--root", str(swift)])
        if hashes != [sha(swift / filename) for filename in ["RESUME.txt", "RESUME.pdf"]]:
            raise AssertionError(f"{name}: independent-process no-op determinism failed")
        pdf = pdf_checks(python, swift, hashlib.sha256(readme).hexdigest())
        report["fixtures"][name] = {"text_bytes_equal": True, "layout_equal": True, "deterministic": True, **pdf}
        print(f"{name}: text/layout/determinism PASS; PDF {pdf}", flush=True)
    invalid = {
        "missing-marker": b"# no markers\n",
        "duplicate-marker": b"<!-- resume:start -->\n" + marked.encode(),
        "reversed-marker": b"<!-- resume:end -->\n<!-- resume:start -->\n",
        "empty-source": b"<!-- resume:start -->\n \n<!-- resume:end -->\n",
        "invalid-utf8": b"<!-- resume:start -->\n\xff\n<!-- resume:end -->\n",
        "setext-heading": b"<!-- resume:start -->\nHeading\n=======\n<!-- resume:end -->\n",
        "missing-glyph": "<!-- resume:start -->\n# Test\n\n\U0001f680\n<!-- resume:end -->\n".encode(),
        "empty-conversion": b"<!-- resume:start -->\n<!-- hidden -->\n<!-- resume:end -->\n",
    }
    for name, readme in invalid.items():
        directory = WORK / "invalid" / name
        fixture(directory, readme, template)
        (directory / "RESUME.pdf").write_bytes(b"existing-pdf")
        before = [sha(directory / filename) for filename in ["RESUME.txt", "RESUME.pdf"]]
        result = subprocess.run([str(binary), "--root", str(directory)], capture_output=True)
        if result.returncode == 0 or not result.stderr:
            raise AssertionError(f"{name}: expected explicit error")
        if before != [sha(directory / filename) for filename in ["RESUME.txt", "RESUME.pdf"]]:
            raise AssertionError(f"{name}: published outputs on failure")
        if (directory / "RESUME.pdf.tmp").exists() or list(directory.glob(".sync-resume-work-*")):
            raise AssertionError(f"{name}: temporary files remain")
        report["failures"].append(name)
    directory = WORK / "invalid" / "operational"
    fixture(directory, fixtures["lf"][0], template)
    (directory / "RESUME.pdf").write_bytes(b"existing-pdf")
    for name, args, env in [
        ("missing-font", ["--font", str(directory / "missing.ttf")], os.environ.copy()),
        ("missing-pandoc", [], {**os.environ, "PATH": str(directory)}),
    ]:
        result = subprocess.run([str(binary), "--root", str(directory), *args], capture_output=True, env=env)
        if result.returncode == 0 or not result.stderr or (directory / "RESUME.txt").read_bytes() != template:
            raise AssertionError(f"{name}: failure was not safe and explicit")
        report["failures"].append(name)
    tools = directory / "tools"
    tools.mkdir(exist_ok=True)
    for name, script in [
        ("pandoc-nonzero", "#!/bin/sh\nprintf 'deliberate pandoc failure\\n' >&2\nexit 23\n"),
        ("pandoc-large-stderr", "#!/bin/sh\nhead -c 200000 /dev/zero >&2\nexit 24\n"),
        ("pandoc-invalid-json", "#!/bin/sh\nprintf 'not json'\n"),
    ]:
        tool = tools / "pandoc"
        tool.write_text(script, encoding="utf-8")
        tool.chmod(0o755)
        result = subprocess.run(
            [str(binary), "--root", str(directory)], capture_output=True, timeout=15,
            env={**os.environ, "PATH": f"{tools}:/usr/bin:/bin"},
        )
        if result.returncode == 0 or not result.stderr:
            raise AssertionError(f"{name}: expected explicit failure")
        if (directory / "RESUME.txt").read_bytes() != template or (directory / "RESUME.pdf").read_bytes() != b"existing-pdf":
            raise AssertionError(f"{name}: changed outputs on conversion failure")
        report["failures"].append(name)
    for name, resume in [
        ("missing-body-marker", b"no markers\n"),
        ("duplicate-body-marker", b"<!-- resume:body:start -->\n" + template),
        ("reversed-body-marker", b"<!-- resume:body:end -->\n<!-- resume:body:start -->\n"),
        ("body-marker-no-lf", template.replace(b"<!-- resume:body:start -->\n", b"<!-- resume:body:start -->\r")),
        ("invalid-printable-utf8", template.replace(b"Preamble", b"\xff")),
    ]:
        fixture(directory, fixtures["lf"][0], resume)
        result = subprocess.run([str(binary), "--root", str(directory)], capture_output=True)
        if result.returncode == 0 or not result.stderr or (directory / "RESUME.txt").read_bytes() != resume:
            raise AssertionError(f"{name}: expected safe explicit failure")
        report["failures"].append(name)
    fixture(directory, fixtures["lf"][0], template)
    temporary = directory / "RESUME.pdf.tmp"
    temporary.mkdir()
    try:
        result = subprocess.run([str(binary), "--root", str(directory)], capture_output=True)
        if result.returncode == 0 or not result.stderr or (directory / "RESUME.txt").read_bytes() != template:
            raise AssertionError("PDF staging failure published outputs")
        report["failures"].append("pdf-staging-failure")
    finally:
        if temporary.exists():
            temporary.rmdir()
    temporary.symlink_to(directory / "missing-target.pdf")
    try:
        result = subprocess.run([str(binary), "--root", str(directory)], capture_output=True)
        if result.returncode == 0 or not result.stderr or (directory / "missing-target.pdf").exists():
            raise AssertionError("Symlink staging path was not rejected")
        report["failures"].append("pdf-staging-symlink")
    finally:
        temporary.unlink()
    text_path = directory / "RESUME.txt"
    text_path.chmod(0o444)
    try:
        result = subprocess.run([str(binary), "--root", str(directory)], capture_output=True)
        if result.returncode == 0 or not result.stderr or text_path.read_bytes() != template:
            raise AssertionError("Text permission failure was not explicit")
        if temporary.exists():
            raise AssertionError("Permission failure left a staged PDF")
        report["failures"].append("text-permission-failure")
    finally:
        text_path.chmod(0o644)
    pdf_path = directory / "RESUME.pdf"
    pdf_path.unlink()
    pdf_path.mkdir()
    try:
        result = subprocess.run([str(binary), "--root", str(directory)], capture_output=True)
        if result.returncode == 0 or not result.stderr or temporary.exists():
            raise AssertionError("PDF replacement failure was not explicit or clean")
        if text_path.read_bytes() == template:
            raise AssertionError("Expected Python-compatible text-first publication before failed PDF replacement")
        report["failures"].append("pdf-replacement-failure-text-first")
    finally:
        pdf_path.rmdir()
    if list(directory.glob(".sync-resume-work-*")):
        raise AssertionError("Operational failure left process scratch files")
    from inspect_resume_pdf import inspect_fixture, write_gallery

    destination = WORK.parent / "pdf-investigation-300dpi"
    destination.mkdir(parents=True, exist_ok=True)
    investigation = {}
    for name, result in report["fixtures"].items():
        investigation[name] = inspect_fixture(name, destination, 300)
        result["similarity_acceptance_failures"] = investigation[name]["acceptance_failures"]
        result["similarity_accepted"] = investigation[name]["locally_accepted"]
    (destination / "report.json").write_text(json.dumps(investigation, indent=2), encoding="utf-8")
    write_gallery(destination, list(investigation))
    report["failed_gates"] = [name for name, result in report["fixtures"].items() if not result["similarity_accepted"]]
    qualified = not report["failed_gates"]
    report["acceptance_policy"] = "Preserved text and similar layout; PDF bytes, reconstructed whitespace and font boxes may differ"
    report["clean_ci_qualified"] = False
    report["decision"] = (
        "LOCAL GO: preserved text and similar layout verified; clean CI qualification required before production migration"
        if qualified else "NO-GO: preserved-text/similar-layout checks failed"
    )
    (WORK / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Qualification report: {WORK / 'report.json'}")
    print(report["decision"])
    print(f"Open PDF gates: {', '.join(report['failed_gates'])}")
    return qualified


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle-only", action="store_true")
    parser.add_argument("--require-parity", action="store_true",
                        help="Exit 2 when local preserved-text/similar-layout checks fail; does not certify CI")
    parser.add_argument("--binary", type=Path, default=ROOT / "scripts/swift-resume/.build/debug/sync-resume")
    args = parser.parse_args()
    wrapping_oracle()
    if not args.oracle_only:
        qualified = qualify(args.binary.resolve())
        if args.require_parity and not qualified:
            sys.exit(2)


if __name__ == "__main__":
    main()
