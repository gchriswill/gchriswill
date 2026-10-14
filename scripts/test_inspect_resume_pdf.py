"""Regression tests for PDF diagnostics, independent of native PDF tools."""

import json
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from inspect_resume_pdf import acceptance_failures, compare_text, descriptors, inferred_baselines, metric_experiment, write_gallery
from qualify_swift_resume import WORK


class PDFInspectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        WORK.parent.mkdir(parents=True, exist_ok=True)

    def test_similarity_accepts_renderer_differences_but_rejects_regressions(self):
        report = {
            "extraction": {"raw": {"bytes_equal": True}, "layout": {"bytes_equal": False}},
            "maximum_word_x_delta_points": 0.00002,
            "maximum_word_y_delta_points": 1.51,
            "inferred_baselines": {"python": {"maximum_error_to_expected_baseline_points": 0},
                                  "swift": {"maximum_error_to_expected_baseline_points": 0.00018}},
            "raster": [{"page": 1, "dpi": 300, "all_lines_have_matching_ink_presence": True,
                        "maximum_line_ink_edge_delta_points": 0.24,
                        "lines": [{"python_ink_pixels_without_swift_neighbor_2px": 0,
                                   "swift_ink_pixels_without_python_neighbor_2px": 0}]}],
        }
        self.assertEqual(acceptance_failures(report), [])
        for field, value in [("maximum_word_x_delta_points", 0.101), ("raster", [])]:
            changed = copy.deepcopy(report)
            changed[field] = value
            self.assertTrue(acceptance_failures(changed))
        changed = copy.deepcopy(report)
        changed["extraction"]["raw"]["bytes_equal"] = False
        self.assertTrue(acceptance_failures(changed))
        for field, value in [("dpi", 72), ("all_lines_have_matching_ink_presence", False),
                             ("maximum_line_ink_edge_delta_points", 0.501)]:
            changed = copy.deepcopy(report)
            changed["raster"][0][field] = value
            self.assertTrue(acceptance_failures(changed))
        changed = copy.deepcopy(report)
        changed["inferred_baselines"]["swift"]["maximum_error_to_expected_baseline_points"] = 0.101
        self.assertTrue(acceptance_failures(changed))
        changed = copy.deepcopy(report)
        changed["raster"][0]["lines"][0]["swift_ink_pixels_without_python_neighbor_2px"] = 1
        self.assertTrue(acceptance_failures(changed))

    def test_extraction_preserves_page_boundary_differences(self):
        result = compare_text("one\n\f  two\n\n", "one\n\f two\n")
        self.assertFalse(result["bytes_equal"])
        difference = result["differences"][0]
        self.assertEqual(difference["page"], 2)
        self.assertEqual(difference["python_blank_lines"], 1)
        self.assertEqual(difference["swift_blank_lines"], 0)
        self.assertTrue(difference["nonblank_lines_equal_ignoring_spaces"])
        self.assertFalse(difference["nonblank_lines_equal"])

    def test_extraction_does_not_hide_missing_characters(self):
        result = compare_text("Unicode: − a\u0301\n", "Unicode: - a\n")
        self.assertFalse(result["differences"][0]["nonblank_lines_equal_ignoring_spaces"])
        with self.assertRaisesRegex(ValueError, "page counts"):
            compare_text("a\f", "a\f\f")

    def test_inferred_baseline_uses_font_descriptor_ascent(self):
        layout = {"lines": [{"page": 1, "text": "Word", "y": 750}]}
        python = inferred_baselines([[{"text": "Word", "yMin": 42 - 759.7656 * 9 / 1000}]], 759.7656, layout)
        cairo = inferred_baselines([[{"text": "Word", "yMin": 42 - 928 * 9 / 1000}]], 928, layout)
        self.assertAlmostEqual(python["maximum_error_to_expected_baseline_points"], 0)
        self.assertAlmostEqual(cairo["maximum_error_to_expected_baseline_points"], 0)
        with self.assertRaisesRegex(ValueError, "Unexpected words"):
            inferred_baselines([[{"text": "Unexpected", "yMin": 10}]], 928, {"lines": []})

    def test_metric_experiment_changes_only_disposable_descriptor(self):
        original = (
            b"%PDF-1.4\n1 0 obj\n<< /Ascent 759.7656 /Descent -240.2344 "
            b"/Type /FontDescriptor >>\nendobj\n2 0 obj\n"
            b"<< /Length 11 >>\nstream\n42 750 Tm\nendstream\nendobj\n"
            b"startxref\n123\n%%EOF\n"
        )
        with tempfile.TemporaryDirectory(dir=WORK.parent) as directory:
            root = Path(directory)
            pdf = root / "original.pdf"
            pdf.write_bytes(original)
            with patch("inspect_resume_pdf.extraction", return_value="same text\n") as extract:
                result = metric_experiment(pdf, {"ascent": 928, "descent": -235}, root, "same text\n")
                extract.assert_called_once()
            diagnostic = (root / "diagnostic-only-reportlab-with-cairo-metrics.pdf").read_bytes()
            self.assertEqual(pdf.read_bytes(), original)
            self.assertEqual(len(diagnostic), len(original))
            self.assertEqual(diagnostic.index(b"42 750 Tm"), original.index(b"42 750 Tm"))
            self.assertEqual(diagnostic.index(b"startxref"), original.index(b"startxref"))
            self.assertEqual(descriptors(root / "diagnostic-only-reportlab-with-cairo-metrics.pdf"),
                             [{"ascent": 928, "descent": -235}])
            self.assertTrue(result["cairo_layout_extraction_reproduced"])
            self.assertEqual(json.loads(json.dumps(result))["descriptor_count"], 1)
            with self.assertRaisesRegex(ValueError, "same-length"):
                metric_experiment(pdf, {"ascent": 123456789, "descent": -235}, root, "text")

    def test_descriptor_errors_are_explicit(self):
        with tempfile.TemporaryDirectory(dir=WORK.parent) as directory:
            path = Path(directory) / "test.pdf"
            path.write_bytes(b"%PDF\n")
            with self.assertRaisesRegex(ValueError, "cannot find"):
                descriptors(path)
            path.write_bytes(b"<< /Ascent 928 /Type /FontDescriptor >>")
            with self.assertRaisesRegex(ValueError, "no Descent"):
                descriptors(path)

    def test_gallery_escapes_labels(self):
        with tempfile.TemporaryDirectory(dir=WORK.parent) as directory:
            root = Path(directory)
            fixture = root / "unicode&"
            fixture.mkdir()
            (fixture / "page-1-preview.png").write_bytes(b"placeholder")
            write_gallery(root, ["unicode&"])
            gallery = (root / "index.html").read_text()
            self.assertIn("unicode&amp;", gallery)
            self.assertIn('href="unicode&amp;/page-1-preview.png"', gallery)
            self.assertIn("not automatic approval", gallery)


if __name__ == "__main__":
    unittest.main()
