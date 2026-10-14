"""Diagnose qualified PDFs without changing their text, fonts, or placement."""

import argparse
import difflib
import html
import json
import math
from pathlib import Path
import re
import statistics
import xml.etree.ElementTree as ET

from qualify_swift_resume import WORK, run, sha


def acceptance_failures(report: dict) -> list[str]:
    """Apply preserved-text/similar-layout criteria, not PDF byte identity."""
    failures = []
    if not report["extraction"]["raw"]["bytes_equal"]:
        failures.append("raw text or reading order differs")
    if report["maximum_word_x_delta_points"] > 0.1:
        failures.append("horizontal word placement differs by more than 0.1 point")
    if any(result["maximum_error_to_expected_baseline_points"] > 0.1
           for result in report["inferred_baselines"].values()):
        failures.append("inferred baseline differs by more than 0.1 point")
    if not report["raster"]:
        failures.append("no raster evidence")
    for page in report["raster"]:
        if page["dpi"] != 300:
            failures.append(f"page {page['page']}: acceptance requires 300-DPI evidence")
        if not page["all_lines_have_matching_ink_presence"]:
            failures.append(f"page {page['page']}: missing or unexpected visible line")
        if page["maximum_line_ink_edge_delta_points"] > 0.5:
            failures.append(f"page {page['page']}: ink-edge difference exceeds 0.5 point")
        if any(line["python_ink_pixels_without_swift_neighbor_2px"]
               or line["swift_ink_pixels_without_python_neighbor_2px"] for line in page["lines"]):
            failures.append(f"page {page['page']}: unmatched dark ink beyond two pixels")
    return failures


def extraction(pdf: Path, options: list[str]) -> str:
    return run(["pdftotext", *options, str(pdf), "-"]).stdout.decode("utf-8")


def descriptors(pdf: Path) -> list[dict[str, float]]:
    data = pdf.read_bytes()
    result = []
    for match in re.finditer(rb"<<(?:(?!>>).)*?/Type /FontDescriptor(?:(?!>>).)*?>>", data, re.S):
        values = {}
        for key in ["Ascent", "Descent"]:
            metric = re.search(rb"/" + key.encode("ascii") + rb"\s+([-.\d]+)", match[0])
            if metric is None:
                raise ValueError(f"{pdf}: font descriptor has no {key}")
            values[key.lower()] = float(metric[1])
        result.append(values)
    if not result:
        raise ValueError(f"{pdf}: cannot find uncompressed font descriptors")
    if len({item["ascent"] for item in result}) != 1:
        raise ValueError(f"{pdf}: multiple font ascents require per-word font mapping")
    return result


def page_words(pdf: Path) -> list[list[dict]]:
    xml = ET.fromstring(run(["pdftotext", "-bbox", str(pdf), "-"]).stdout)
    pages = []
    for page in xml.iter():
        if page.tag.endswith("}page"):
            pages.append([
                {"text": node.text, **{key: float(value) for key, value in node.attrib.items()}}
                for node in page.iter() if node.tag.endswith("}word")
            ])
    if not pages:
        raise ValueError(f"{pdf}: no PDF pages")
    return pages


def compare_text(python: str, swift: str) -> dict:
    pages = [text.split("\f") for text in [python, swift]]
    if len(pages[0]) != len(pages[1]):
        raise ValueError("Text extraction page counts differ")
    differences = []
    for number, (p, s) in enumerate(zip(*pages), 1):
        if p == s:
            continue
        p_lines, s_lines = p.splitlines(), s.splitlines()
        p_nonblank = [line for line in p_lines if line.strip()]
        s_nonblank = [line for line in s_lines if line.strip()]
        differences.append({
            "page": number,
            "python_blank_lines": len(p_lines) - len(p_nonblank),
            "swift_blank_lines": len(s_lines) - len(s_nonblank),
            "nonblank_lines_equal": p_nonblank == s_nonblank,
            "nonblank_lines_equal_ignoring_spaces": (
                [line.split() for line in p_nonblank] == [line.split() for line in s_nonblank]
            ),
            "diff": "".join(difflib.unified_diff(
                p.splitlines(keepends=True), s.splitlines(keepends=True),
                fromfile="ReportLab", tofile="Cairo",
            )),
        })
    return {"bytes_equal": python == swift, "differences": differences}


def metric_experiment(python_pdf: Path, target: dict[str, float], output: Path,
                      expected: str) -> dict:
    original = python_pdf.read_bytes()
    changed = 0

    def replace_descriptor(match: re.Match[bytes]) -> bytes:
        nonlocal changed
        descriptor = match[0]
        for field in ["Ascent", "Descent"]:
            pattern = rb"(/" + field.encode("ascii") + rb"\s+)([-.\d]+)"

            def replace_number(number: re.Match[bytes]) -> bytes:
                value = f"{target[field.lower()]:g}".encode("ascii")
                if len(value) > len(number[2]):
                    raise ValueError("Metric experiment requires same-length, xref-preserving edits")
                return number[1] + value.ljust(len(number[2]), b" ")

            descriptor, count = re.subn(pattern, replace_number, descriptor)
            if count != 1:
                raise ValueError(f"Expected one {field} per experiment descriptor")
        changed += 1
        return descriptor

    experimental = re.sub(
        rb"<<(?:(?!>>).)*?/Type /FontDescriptor(?:(?!>>).)*?>>",
        replace_descriptor, original, flags=re.S,
    )
    if changed == 0 or len(experimental) != len(original):
        raise ValueError("Metric experiment did not preserve PDF byte offsets")
    path = output / "diagnostic-only-reportlab-with-cairo-metrics.pdf"
    path.write_bytes(experimental)
    text = extraction(path, ["-layout"])
    (output / "metric-experiment-layout.txt").write_text(text, encoding="utf-8")
    return {
        "purpose": "Causal diagnostic only; not a renderer fix or a qualified output",
        "changed_fields_only": ["FontDescriptor.Ascent", "FontDescriptor.Descent"],
        "drawing_streams_fonts_and_xref_offsets_unchanged": True,
        "cairo_layout_extraction_reproduced": text == expected,
        "descriptor_count": changed,
    }



def inferred_baselines(words: list[list[dict]], ascent: float, layout: dict) -> dict:
    errors = []
    for number, page in enumerate(words, 1):
        expected = [792 - line["y"] for line in layout["lines"]
                    if line["page"] == number and line["text"].strip()]
        if page and not expected:
            raise ValueError(f"Unexpected words on page {number}")
        for word in page:
            baseline = word["yMin"] + ascent * 9 / 1000
            errors.append(min(abs(baseline - y) for y in expected))
    return {
        "method": "Poppler yMin + embedded font Ascent * 9 / 1000, in top-origin points",
        "word_count": len(errors),
        "maximum_error_to_expected_baseline_points": max(errors, default=0),
    }


def ink_bounds(image, origin: tuple[int, int], scale: float):
    bounds = image.getbbox()
    if bounds is None:
        return None
    return [(coordinate + origin[index % 2]) / scale for index, coordinate in enumerate(bounds)]


def compare_rasters(python: Path, swift: Path, output: Path, layout: dict, dpi: int) -> list[dict]:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter

    scale = dpi / 72
    pages = max(line["page"] for line in layout["lines"])
    for name, directory in [("python", python), ("swift", swift)]:
        prefix = output / name
        run(["pdftoppm", "-r", str(dpi), "-gray", str(directory / "RESUME.pdf"), str(prefix)])
    sources = {
        name: sorted(output.glob(f"{name}-*.pgm"), key=lambda path: int(path.stem.split("-")[-1]))
        for name in ["python", "swift"]
    }
    if any(len(paths) != pages for paths in sources.values()):
        raise ValueError("Raster page count does not match the layout")
    results = []
    for number, (p, s) in enumerate(zip(sources["python"], sources["swift"]), 1):
        with Image.open(p) as a, Image.open(s) as b:
            if a.size != b.size or a.size != (round(612 * scale), round(792 * scale)):
                raise ValueError("Raster dimensions do not match Letter geometry")
            mask_a = a.point(lambda value: 255 if value < 128 else 0)
            mask_b = b.point(lambda value: 255 if value < 128 else 0)
            delta = ImageChops.difference(a, b)
            missing_a = ImageChops.subtract(mask_a, mask_b.filter(ImageFilter.MaxFilter(5)))
            missing_b = ImageChops.subtract(mask_b, mask_a.filter(ImageFilter.MaxFilter(5)))
            line_results = []
            crops = []
            for line_number, line in enumerate(layout["lines"], 1):
                if line["page"] != number:
                    continue
                baseline = 792 - line["y"]
                top = math.floor((baseline - 9) * scale)
                bottom = math.floor((baseline + 3) * scale)
                box = (0, top, a.width, bottom)
                crop_a, crop_b = mask_a.crop(box), mask_b.crop(box)
                bounds_a = ink_bounds(crop_a, (0, top), scale)
                bounds_b = ink_bounds(crop_b, (0, top), scale)
                line_results.append({
                    "layout_line": line_number, "text": line["text"], "baseline_points": baseline,
                    "python_ink_bounds_points": bounds_a, "swift_ink_bounds_points": bounds_b,
                    "ink_presence_equal": (bounds_a is None) == (bounds_b is None),
                    "maximum_ink_edge_delta_points": (
                        max(abs(x - y) for x, y in zip(bounds_a, bounds_b))
                        if bounds_a is not None and bounds_b is not None else None
                    ),
                    "python_ink_pixels_without_swift_neighbor_2px": sum(missing_a.crop(box).histogram()[1:]),
                    "swift_ink_pixels_without_python_neighbor_2px": sum(missing_b.crop(box).histogram()[1:]),
                })
                if line["text"].strip():
                    crops.append((line, a.crop(box), b.crop(box), ImageChops.invert(delta.crop(box))))
            if not all(item["ink_presence_equal"] for item in line_results):
                raise AssertionError(f"Page {number}: missing or unexpected visible line")
            result = {
                "page": number, "dpi": dpi, "size_pixels": a.size,
                "python_ink_bounds_points": ink_bounds(mask_a, (0, 0), scale),
                "swift_ink_bounds_points": ink_bounds(mask_b, (0, 0), scale),
                "changed_pixels": a.width * a.height - delta.histogram()[0],
                "maximum_line_ink_edge_delta_points": max(
                    (item["maximum_ink_edge_delta_points"] for item in line_results
                     if item["maximum_ink_edge_delta_points"] is not None), default=0,
                ),
                "all_lines_have_matching_ink_presence": True,
                "lines": line_results,
            }
            results.append(result)
            a.save(output / f"page-{number}-reportlab-{dpi}dpi.png")
            b.save(output / f"page-{number}-cairo-{dpi}dpi.png")
            preview = Image.new("L", (1800, 800), 255)
            draw = ImageDraw.Draw(preview)
            for index, (image, label) in enumerate([
                (a, "ReportLab"), (b, "Cairo"), (ImageChops.invert(delta), "Pixel difference (not an acceptance threshold)"),
            ]):
                image = image.copy()
                image.thumbnail((600, 776))
                preview.paste(image, (index * 600, 24))
                draw.text((index * 600 + 8, 5), f"Page {number}: {label}", fill=0)
            preview.save(output / f"page-{number}-preview.png")
            for label, entry in ([("top", crops[0]), ("bottom", crops[-1])] if crops else []):
                line, ca, cb, cd = entry
                # Keep 300-DPI source pixels readable in a narrow stacked crop.
                width = min(a.width, 1600)
                left = max(0, math.floor(42 * scale) - 8)
                sheet = Image.new("L", (width, (ca.height + 24) * 3), 255)
                draw = ImageDraw.Draw(sheet)
                for row, (image, engine) in enumerate([(ca, "ReportLab"), (cb, "Cairo"), (cd, "Pixel difference")]):
                    y = row * (ca.height + 24)
                    draw.text((4, y + 3), f"{engine}: page {number} {label}, baseline {792 - line['y']:g} pt", fill=0)
                    sheet.paste(image.crop((left, 0, min(left + width, a.width), image.height)), (0, y + 24))
                sheet.save(output / f"page-{number}-{label}-detail.png")
            # Full-resolution band sheets make every visible line reviewable without a huge page image.
            for first in range(0, len(crops), 12):
                batch = crops[first:first + 12]
                width = min(a.width, math.ceil(570 * scale))
                sheet = Image.new("L", (width * 2, sum(ca.height + 24 for _, ca, _, _ in batch)), 255)
                draw = ImageDraw.Draw(sheet)
                row = 0
                for line, ca, cb, _ in batch:
                    draw.text((4, row + 2), f"ReportLab baseline {792 - line['y']:g} pt", fill=0)
                    draw.text((width + 4, row + 2), "Cairo (same absolute coordinates)", fill=0)
                    sheet.paste(ca.crop((0, 0, width, ca.height)), (0, row + 24))
                    sheet.paste(cb.crop((0, 0, width, cb.height)), (width, row + 24))
                    row += ca.height + 24
                sheet.save(output / f"page-{number}-bands-{first // 12 + 1}.png")
            if output.name in ["unicode", "unicode-renderer", "lf", "crlf"]:
                for offset, (line, ca, cb, cd) in enumerate(crops):
                    if "Aliases:" not in line["text"] and "Unicode:" not in line["text"]:
                        continue
                    bounds = ImageChops.invert(ca).getbbox()
                    other = ImageChops.invert(cb).getbbox()
                    if bounds is None or other is None:
                        raise AssertionError("Unicode line has no visible ink")
                    left = max(0, min(bounds[0], other[0]) - 10)
                    right = min(ca.width, max(bounds[2], other[2]) + 10)
                    sheet = Image.new("L", (right - left, (ca.height + 24) * 3), 255)
                    draw = ImageDraw.Draw(sheet)
                    for row, (image, label) in enumerate([(ca, "ReportLab"), (cb, "Cairo"), (cd, "Pixel difference")]):
                        y = row * (ca.height + 24)
                        draw.text((4, y + 3), label, fill=0)
                        sheet.paste(image.crop((left, 0, right, image.height)), (0, y + 24))
                    sheet.save(output / f"page-{number}-unicode-{offset}.png")
        p.unlink()
        s.unlink()
    return results


def inspect_fixture(name: str, destination: Path, dpi: int) -> dict:
    python = WORK / name / "python"
    swift = WORK / name / "swift"
    output = destination / name
    output.mkdir(parents=True, exist_ok=True)
    layout = json.loads((swift / "layout.json").read_text(encoding="utf-8"))
    input_hashes = {engine: sha(directory / "RESUME.pdf")
                    for engine, directory in [("python", python), ("swift", swift)]}
    texts = {}
    geometry = {}
    fonts = {}
    words = {}
    for engine, directory in [("python", python), ("swift", swift)]:
        pdf = directory / "RESUME.pdf"
        fonts[engine] = descriptors(pdf)
        words[engine] = page_words(pdf)
        geometry[engine] = inferred_baselines(words[engine], fonts[engine][0]["ascent"], layout)
        texts[engine] = {
            "layout": extraction(pdf, ["-layout"]),
            "raw": extraction(pdf, ["-raw"]),
            "fixed": extraction(pdf, ["-layout", "-fixed", str(layout["characterWidth"])]),
        }
        for mode, text in texts[engine].items():
            (output / f"{engine}-{mode}.txt").write_text(text, encoding="utf-8")
    offsets = []
    horizontal_offsets = []
    for p_page, s_page in zip(words["python"], words["swift"]):
        if [w["text"] for w in p_page] != [w["text"] for w in s_page]:
            raise AssertionError(f"{name}: PDF words or page allocation differ")
        offsets.extend(p["yMin"] - s["yMin"] for p, s in zip(p_page, s_page))
        horizontal_offsets.extend(abs(p["xMin"] - s["xMin"]) for p, s in zip(p_page, s_page))
    if len(words["python"]) != len(words["swift"]):
        raise AssertionError(f"{name}: page counts differ")
    predicted = (fonts["swift"][0]["ascent"] - fonts["python"][0]["ascent"]) * 9 / 1000
    modes = {mode: compare_text(texts["python"][mode], texts["swift"][mode]) for mode in ["layout", "raw", "fixed"]}
    if not modes["raw"]["bytes_equal"]:
        raise AssertionError(f"{name}: raw extraction differs; investigate characters or reading order")
    for mode, result in modes.items():
        (output / f"{mode}.diff").write_text(
            "".join(item["diff"] for item in result["differences"]), encoding="utf-8",
        )
    experiment = metric_experiment(python / "RESUME.pdf", fonts["swift"][0], output, texts["swift"]["layout"])
    experimental_words = page_words(output / "diagnostic-only-reportlab-with-cairo-metrics.pdf")
    if [[w["text"] for w in page] for page in experimental_words] != [
        [w["text"] for w in page] for page in words["swift"]
    ]:
        raise AssertionError("Metric experiment changed words or page allocation")
    experiment["maximum_bbox_top_delta_to_cairo_points"] = max(
        (abs(p["yMin"] - s["yMin"]) for p_page, s_page in zip(experimental_words, words["swift"])
         for p, s in zip(p_page, s_page)), default=0,
    )
    experiment["reportlab_layout_extraction_unchanged"] = (
        (output / "metric-experiment-layout.txt").read_text(encoding="utf-8") == texts["python"]["layout"]
    )
    result = {
        "input_pdf_sha256": input_hashes,
        "font_descriptors": fonts,
        "predicted_bbox_top_offset_points": predicted,
        "observed_bbox_top_offset_median_points": statistics.median(offsets) if offsets else None,
        "maximum_bbox_offset_residual_points": max((abs(offset - predicted) for offset in offsets), default=0),
        "maximum_word_x_delta_points": max(horizontal_offsets, default=0),
        "inferred_baselines": geometry,
        "extraction": modes,
        "font_metric_experiment": experiment,
        "raster": compare_rasters(python, swift, output, layout, dpi),
        "review_status": "similarity policy approved after prior visual review; this run performs automated checks",
    }
    if input_hashes != {engine: sha(directory / "RESUME.pdf")
                        for engine, directory in [("python", python), ("swift", swift)]}:
        raise AssertionError("Inspection modified an input PDF")
    result["acceptance_failures"] = acceptance_failures(result)
    result["locally_accepted"] = not result["acceptance_failures"]
    return result


def write_gallery(destination: Path, fixtures: list[str], dpi: int = 300) -> None:
    sections = []
    for name in fixtures:
        images = sorted((destination / name).glob("page-*.png"))
        sections.append(f"<h2>{html.escape(name)}</h2>")
        for image in images:
            relative = image.relative_to(destination).as_posix()
            if f"-{dpi}dpi.png" in image.name:
                sections.append(f'<p><a href="{html.escape(relative, quote=True)}">'
                                f'{html.escape(image.name)} (full-resolution page)</a></p>')
                continue
            sections.append(
                f'<p>{html.escape(image.name)}</p><a href="{html.escape(relative, quote=True)}">'
                f'<img loading="lazy" src="{html.escape(relative, quote=True)}" alt="{html.escape(image.name)}"></a>'
            )
    (destination / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Resume PDF investigation</title>'
        '<style>body{font:16px sans-serif;margin:24px}img{max-width:100%;border:1px solid #aaa}</style>'
        f'<h1>Resume PDF investigation</h1><p>{dpi}-DPI source rasters; previews are resized. '
        'Band sheets preserve source pixels. Click images for full size. '
        'Differences are diagnostic, not automatic approval.</p>' + "".join(sections) + "</html>",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dpi", type=int, default=300)
    args = parser.parse_args()
    if args.dpi < 150 or args.dpi > 600:
        parser.error("--dpi must be between 150 and 600")
    qualification = json.loads((WORK / "report.json").read_text(encoding="utf-8"))
    destination = WORK.parent / f"pdf-investigation-{args.dpi}dpi"
    destination.mkdir(parents=True, exist_ok=True)
    report = {}
    for name in qualification["fixtures"]:
        report[name] = inspect_fixture(name, destination, args.dpi)
        entry = report[name]
        print(
            f"{name}: raw text equal; bbox residual {entry['maximum_bbox_offset_residual_points']:.6f} pt; "
            f"{len(entry['raster'])} pages rendered at {args.dpi} DPI", flush=True,
        )
    (destination / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_gallery(destination, list(report), args.dpi)
    print(f"Investigation: {destination / 'report.json'}")
    print("Local similarity checks complete. Production migration still requires clean CI qualification.")


if __name__ == "__main__":
    main()
