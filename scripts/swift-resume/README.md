# Swift resume exporter qualification

## Status: locally qualified; clean CI required before migration

This implements the Cairo + FreeType qualification path from the migration
assessment. The [production workflow](../../.github/workflows/sync-resume.yml)
now calls clean qualification before publishing the qualified Swift exports.
[`../sync_resume.py`](../sync_resume.py) remains the differential baseline and
rollback generator. Checked-in exports, canonical resume, and download links
have not been changed locally.

The Swift executable retains Pandoc, uses pinned pure-Swift CryptoSwift for
SHA-256, and imports Cairo/FreeType directly through SwiftPM system-library
modules. There is no Python renderer helper, browser engine, custom PDF writer,
or silent renderer fallback.

The user approved preserved text and very similar layout rather than exact
PDF identity. The reviewed renderer-specific font boxes, reconstructed
whitespace, and small stroke-edge differences are acceptable under that
requirement. Local qualification passes. Production migration remains gated
on clean Ubuntu CI qualification; no remote run has been performed. That gate
is enforced by the production job dependency, not by a claimed local CI pass.

## Clean Ubuntu CI gate

The read-only [qualification workflow](../../.github/workflows/qualify-swift-resume.yml)
is ready for publication. It runs on relevant pushes, pull requests, and manual
dispatches using a fresh Ubuntu 24.04 runner and pinned Swift 6.3.2. Swift is
installed from the official swift.org tarball only after its pinned SHA-256 and
the Swift 6.x release-signing-key signature are verified. It installs
Ubuntu build/inspection dependencies normally, without the locally extracted
packages or existing build products.

The workflow requires the committed dependency lockfile, checks the exact font
hash, runs the Python regressions and all Swift tests with the 1,565-case Python
wrapping oracle, and qualifies two independently compiled release builds. Both
builds must pass all nine fixtures and 22 explicit failure scenarios, and their
generated TXT/PDF hashes must match. It verifies production files are untouched.
Environment versions, commit identity, reports, hashes, and the 300-DPI gallery
are uploaded for 14 days, including available evidence after failures.
After success only, the actual-resume Swift exports are uploaded separately
with the source hash, output hashes, and commit identity.
Two standard-library publication regression tests exercise the exact workflow
handoff scripts, checking repeatability and rejection of wrong commits,
modified sources, corrupt exports, and missing artifacts before output writes.
The qualified artifact is named by run ID so a retry of only the publication
job can consume the already successful qualification.

The harness's `clean_ci_qualified: false` remains deliberate: a local script
cannot certify its execution environment. Clean CI evidence is the successful
workflow run for the exact commit, its job summary, and uploaded artifacts.
On main, **Sync RESUME** calls this same reusable qualification workflow with
read-only permissions. Its write-capable job cannot start unless qualification
and artifact publication succeed. It checks out the exact qualified commit,
validates the artifact commit and source/output hashes, then copies those
already tested exports; it does not rebuild with potentially different
dependencies. Main-only execution, serialization, manual dispatch, and the
no-change commit guard remain intact. A newer main commit causes the ordinary
non-fast-forward push to fail rather than overwrite newer content.

Publishing these workspace changes activates the gate. On the first successful
main run it will regenerate the checked-in exports with Swift automatically.
Standalone qualification on branches or pull requests never writes exports.
Review the uploaded evidence and investigate failures rather than relaxing
gates to hide package/toolchain drift. No branch has been published and no
GitHub run is claimed by this local setup.

For local Swift regeneration after an accepted CI run, build with the pinned
toolchain and dependencies described below, then run from the repository root:

```sh
swift build -c release --package-path scripts/swift-resume --force-resolved-versions
scripts/swift-resume/.build/release/sync-resume --root "$PWD"
```

Repeat the invocation and check that the export hashes are unchanged. To roll
back, restore the production workflow's Python invocation/dependencies and
regenerate with `python3 scripts/sync_resume.py`. Keep that baseline available
for qualification even after migration.

## Requirements

The implementation was built and exercised on Ubuntu 24.04 with:

| Component | Qualified local version |
| --- | --- |
| Swift | 6.3.2 |
| CryptoSwift | 1.9.0, revision pinned in [`Package.resolved`](Package.resolved) |
| Cairo | Ubuntu `1.18.0-3build1` |
| FreeType | Ubuntu `2.13.2+dfsg-1ubuntu0.2` |
| Pandoc | Ubuntu `3.1.3+ds-2` |
| ReportLab (baseline only) | Ubuntu `4.1.0-4` |
| Poppler (inspection only) | Ubuntu `24.02.0-1ubuntu9.10` |
| DejaVu fonts | Ubuntu `2.37-8` |

The runtime dependencies are Pandoc, Cairo, FreeType, and the exact
`/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf` file. Its tested SHA-256 is
`c805f9436dbc268644c1d9584f01a601a653e028e08fd74b9b949f6cf8304d88`.
The Cairo PDF metadata API requires Cairo 1.16 or newer.

On a prepared Ubuntu machine, the relevant packages are `pkg-config`,
`libcairo2-dev`, `libfreetype-dev`, `pandoc`, `fonts-dejavu-core`,
`python3-reportlab`, and `poppler-utils`. ReportLab and its Pillow dependency
are only used by the test harness. They are not Swift runtime dependencies.

For this implementation, missing packages were downloaded and extracted into
the ignored repository-local `.qualification/deps` directory, not installed
system-wide. No toolchain or system configuration was changed. That local
directory is validation support, not a vendored production dependency.

## Reproducing qualification

Run these commands from the repository root with the dependencies available:

```sh
python3 scripts/qualify_swift_resume.py --oracle-only
RESUME_WRAP_ORACLE="$PWD/.qualification/outputs/wrapping.json" \
  swift test --package-path scripts/swift-resume
swift build -c release --package-path scripts/swift-resume
python3 scripts/qualify_swift_resume.py \
  --binary scripts/swift-resume/.build/release/sync-resume
```

The wrapping oracle is generated from the selected Python interpreter, not
from hand-authored expected strings. Without `RESUME_WRAP_ORACLE`, the ordinary
Swift unit tests run but the differential wrapping test explicitly skips.

The qualification harness uses fresh disposable copies of the current README,
text template, and Python generator under `.qualification/outputs`. It never
runs either exporter against the repository's production outputs. Existing
fixtures are overwritten when it runs; that directory is disposable.

To use the locally extracted dependencies in this workspace:

```sh
export PATH="$PWD/.qualification/bin:$PWD/.qualification/deps/usr/bin:$PATH"
export LD_LIBRARY_PATH="$PWD/.qualification/deps/usr/lib/x86_64-linux-gnu"
export PYTHONPATH="$PWD/.qualification/deps/usr/lib/python3/dist-packages"
export PKG_CONFIG_PATH="$PWD/.qualification/deps/usr/lib/x86_64-linux-gnu/pkgconfig:$PWD/.qualification/deps/usr/share/pkgconfig"
export PKG_CONFIG_SYSROOT_DIR="$PWD/.qualification/deps"
```

The ignored `.qualification/bin/pandoc` launcher supplies the relocated Pandoc
data directory; it does not change the production conversion arguments. Use
`--cache-path .qualification/swift-cache` on Swift commands to keep dependency
caches local as well.

If Git's `safe.bareRepository=explicit` policy prevents SwiftPM from resolving
its bare dependency checkout, a per-command override was needed locally:

```sh
GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.bareRepository GIT_CONFIG_VALUE_0=all \
  swift build -c release --package-path scripts/swift-resume \
  --cache-path .qualification/swift-cache
```

This does not modify Git configuration. It is not required on machines without
that policy; only use it for this known dependency-resolution operation.

The harness writes a JSON report, drawing-stream inspection files, page
rasterizations, and a first-page comparison image (Python, Swift, pixel
difference). Its normal exit status indicates whether the assessment ran
successfully, **not** whether migration is approved. It prints the local
qualification decision explicitly. For an acceptance-gate invocation:

```sh
python3 scripts/qualify_swift_resume.py \
  --binary scripts/swift-resume/.build/release/sync-resume --require-parity
```

This now exits **0** when preserved-text/similar-layout checks pass, or **2**
when those local checks fail. Unexpected conversion, test, or inspection
failures exit nonzero separately. A local pass does not certify clean CI or
authorize production writes.

### Current acceptance criteria

PDF bytes, raw font bounding boxes, and Poppler's inferred layout whitespace
need not match. The acceptance gate regenerates and checks all nine fixtures,
including 300-DPI raster evidence from the current PDFs, rather than trusting
a cached report:

- Preserve exact text-export bytes and raw PDF extraction, including page
  boundaries and reading order.
- Retain the existing line/page plan, Letter geometry, embedded font,
  title/subject, dates, and independently deterministic regeneration.
- Keep horizontal word positions and ascent-corrected inferred baselines
  within 0.1 point of their expected positions.
- Preserve visible-ink presence on every line, allowing up to 0.5 point of
  thresholded ink-edge variation and requiring every dark pixel to have a
  counterpart within two pixels at 300 DPI (0.48 point).

The small raster tolerances operationalize "very similar" without requiring
pixel identity. They are separate from the tighter layout-position checks.
Seven regression tests verify that tolerated renderer differences pass but
missing text, shifted baselines, missing ink, and excessive raster differences
fail. No visible coordinates or font descriptors were changed to satisfy
these criteria.

## Implemented contract

- Hash the entire README's exact bytes, including content outside the resume.
- Select one ordered pair of complete-line source/body markers; validate
  selected UTF-8 and reject empty source/conversion output.
- Preserve links recursively through a heterogeneous Codable Pandoc AST.
- Preserve source top-level ATX heading spacing, ignoring fences and rejecting
  heading mismatches or missing spacing sentinels.
- Preserve the text template's preamble/suffix bytes, body LF/CRLF convention,
  digest marker, and final-newline behavior.
- Match Python whitespace, tab stops, Unicode scalar lengths, indentation,
  long-word wrapping, and disabled hyphen splitting.
- Derive wrapping columns from the unhinted font-unit `M` advance; render
  Letter pages at 9 points with 12-point baselines and 42-point margins.
- Retain blank lines and the inclusive bottom baseline at 42 points; map
  ReportLab's baseline to Cairo's inverted coordinate system.
- Embed the exact font, reject missing glyphs/NUL, and draw with UTF-8 text
  clusters for selectable Unicode text.
- Keep title, exact digest subject, and invariant creation/modification dates.
  Cairo truthfully identifies itself as producer rather than impersonating
  ReportLab.
- Keep native font resources alive through Cairo caches using a font-face
  destruction callback; check native statuses, including delayed write errors.
- Capture Pandoc stdout/stderr through workspace-local files, avoiding pipe
  deadlocks, and surface failures explicitly.

Supply an explicit `--root` (a disposable directory during qualification);
invocation is independent of the
caller's working directory. Optional `--layout <json>` emits the exact line
sequence supplied to the renderer, and `--font <ttf>` supports failure tests.

PDF staging precedes text publication, followed by POSIX replacement of the
PDF. This retains the existing **non-atomic two-file** semantics: if final PDF
replacement fails, the new text can already be published. Tests verify this
behavior and cleanup. The exporter intentionally rejects a non-regular
staging path, including a broken symlink, rather than following it or deleting
an existing directory.

## Observed results and open gates

The fresh baseline matters: the committed text is not the current generator's
exact output, so comparing only against the checked-in exports would be wrong.

- Six Swift tests passed, including **1,565** differential wrapping cases.
- **Nine** end-to-end fixtures passed byte-identical text and identical
  wrapped-line/page/baseline plans: actual resume, LF, CRLF, an outside-resume
  digest change, Unicode aliases/combining marks, pagination, simple
  paragraphs, nested headings, and direct decomposed Unicode in the preamble.
- All nine passed identical extracted PDF words, Letter geometry, page
  counts, embedded Unicode font checks, title/subject, and separate-process
  no-op text/PDF hashes. The actual resume remains six pages.
- An independent clean local release build produced identical actual-resume
  text/PDF hashes; the full fixture assessment also ran against that binary.
  This is local evidence, not a substitute for clean Ubuntu CI qualification.
- **22** failure scenarios passed, including malformed source/template
  markers, invalid UTF-8, empty conversions, unsupported headings, missing
  glyph/font/Pandoc, nonzero/large-stderr/invalid-JSON Pandoc, PDF staging and
  symlink failures, text permissions, and text-first PDF replacement failure.
- Full `pdftotext -layout` bytes differ for the actual, Unicode, and pagination
  fixtures. Poppler word x positions differ by less than 0.00002 point, but
  word bounding-box y positions differ by approximately **1.5143 points**,
  outside the original assessment's raw-bounding-box inspection threshold.
  Raw font boxes are now diagnostic; physical layout similarity is evaluated
  using inferred baselines and raster evidence.

Inspection identifies different embedded font-descriptor ascent values:
ReportLab emits `759.7656`, Cairo emits `928`, in 1000-unit font space. Their
9-point difference explains approximately 1.5141 points of the bounding-box
offset. The drawing streams put the first visible baseline at the same
physical position: ReportLab uses `(42, 750)`; Cairo uses `(42, 42)` under its
page-flipping transform. **Bounding-box differences are not evidence that
the drawn baseline moved.** Shifting visible text to compensate would break
the layout contract and is not an acceptable fix.

The follow-up inspection below covers all six actual-resume pages and Unicode
comparisons using 300-DPI source rasters. Structure, wrapping, and placement
appear consistent, but rasterization is not identical. Diagnostics are not an
automatic acceptance of renderer differences or a replacement for clean CI.

Local performance observations, not a general benchmark:

- Cold release builds: about 25.9 and 31.0 seconds, maximum RSS about 607 MiB.
- Warm no-change release build: about 0.7 seconds.
- Actual-resume generation: approximately 0.32 seconds for Python versus
  0.47 seconds for the release Swift executable in one paired run.
- Release executable: about 4.2 MiB; CryptoSwift checkout: about 2.1 MiB.
  The local extracted development/test dependencies occupy about 226 MiB,
  which is not the minimal runtime footprint.

No speed improvement is claimed. Repeat timing and determinism in a clean,
pinned Ubuntu CI environment before drawing operational conclusions.

The decision is **local go, pending clean CI** under the approved similarity
requirement. A libharu fallback is not needed on current evidence. The production
configuration now enforces clean qualification before any Swift exports can
be published. Its main-only, serialized, manually dispatchable behavior and
no-change commit guard are preserved.

## Follow-up: extraction and 300-DPI visual investigation

Run after the qualification harness, with the same local dependency environment:

```sh
python3 scripts/inspect_resume_pdf.py
python3 -m unittest discover -s scripts -p 'test_inspect_resume_pdf.py' -v
```

[`../inspect_resume_pdf.py`](../inspect_resume_pdf.py) writes reproducible
evidence under the ignored `.qualification/pdf-investigation-300dpi` directory:

- `report.json`: per-page extraction differences, font descriptors, inferred
  baselines, per-line ink bounds, and controlled experiment results.
- `index.html`: review gallery with full-resolution lossless page PNGs,
  page previews, 300-DPI line bands, boundary crops, and Unicode close-ups.
- Extracted text in raw, layout, and explicit fixed-character-width modes,
  plus readable diffs.
- Clearly labeled `diagnostic-only-reportlab-with-cairo-metrics.pdf` copies.

Input PDFs are hashed before and after inspection and must remain unchanged.
Temporary PGM rasters are deleted after lossless PNG evidence is saved.
The diagnostic regression tests use only Python's standard library; raster
inspection reuses Pillow, already present for the ReportLab baseline.
With repository-local extracted packages, the editor's system interpreter may
still report `reportMissingImports` for `PIL`; the executed inspection resolves
it through the documented `PYTHONPATH`. No editor settings were changed to
hide that environment diagnostic.

### Extraction findings

All **nine** fixtures have byte-identical `pdftotext -raw` output, including
page boundaries. No lost characters or changed reading order were observed.
The `pdftotext -layout` differences are:

| Fixture | Observed difference | Additional evidence |
| --- | --- | --- |
| Actual resume | One fewer inferred blank line before `Certifications` on page 5 | Nonblank lines match exactly; drawn blank-line spacing and heading placement match |
| Unicode | `Preamble` tab spacing inferred as four spaces versus three | Supplying the measured 5.41845703125-point fixed character width yields identical extraction |
| Pagination | Code indentation inferred with a different number of spaces | Supplying the measured fixed character width yields identical extraction on every page |
| Other six fixtures | None | Raw and layout extraction match |

These are extraction/reconstruction differences, not lost source spacing in
the text export. Fixed-width extraction remains diagnostic, not a replacement
oracle. Raw text equality and the approved visual/position checks now enforce
the user's clarified requirement.

The original Markdown Unicode fixture is normalized by Pandoc: its decomposed
`a` + acute becomes precomposed `á` before rendering. The added
`unicode-renderer` fixture deliberately bypasses that normalization by putting
decomposed acute/ring characters in the preserved text preamble, alongside
hyphen/minus aliases, nonbreaking spaces, curly quotes, and ellipsis. The
renderers produce matching words, raw extraction, layout extraction, and
visually matching glyphs. Poppler normalizes the nonbreaking space to an
ordinary space in both PDFs. The existing unshaped combining-mark placement
is preserved rather than silently replaced with a new shaping behavior.

### Bounding boxes versus drawn baselines

The ascent difference predicts **1.5141096 points** of bounding-box offset.
Across all fixture words, the maximum residual after accounting for that
ascent difference is less than **0.00018 point**. Baselines inferred from
`yMin + Ascent * 9 / 1000` likewise match the expected drawn baselines within
0.00018 point. This separates font-box reporting from visible text placement;
the inference method is reported explicitly, not presented as a direct
measurement of the PDF text matrices.

A controlled experiment changes only the ReportLab copy's font-descriptor
ascent/descent values to Cairo's values, preserving byte lengths and xref
offsets. It does not change glyph/font streams, text, or drawing coordinates.
This reproduces Cairo's bounding-box tops within 0.00018 point, **but leaves
ReportLab's layout-extraction spacing unchanged**. Therefore:

- The bounding-box offset is explained by font-descriptor metrics.
- Those ascent/descent fields alone do **not** explain the whitespace
  reconstruction differences. Neither metric edits nor moving baselines
  would be a justified production fix.

The experiment PDFs are investigative copies, not candidate exports. No
metadata rewriting or PDF postprocessing was added to the exporter.

### Visual review findings

Both engines' **16 fixture pages** were rasterized at 300 DPI. Automated
diagnostics checked every planned line and blank line at unchanged absolute
coordinates:

- Every line has matching visible-ink presence.
- The maximum thresholded ink-edge difference is **one pixel / 0.24 point**.
- Every dark pixel has a counterpart within a two-pixel neighborhood in the
  other renderer. This 0.48-point neighborhood is now part of the explicit
  local similarity criterion, alongside the 0.5-point ink-edge limit.
- No page-edge clipping, unexpected visible line, or pagination drift was
  observed. The actual resume still has six pages.

All six actual-resume page previews were inspected side by side, along with
300-DPI bottom-boundary details for each page and Unicode close-ups for LF,
CRLF, the normalized Unicode fixture, and direct decomposed Unicode.
Wrapping, heading spacing, nested indentation, long links, punctuation, and
bottom-of-page continuation appear consistent. Detailed crops show small
stroke-edge/rasterization differences, not a 1.51-point visible baseline
shift. This review is not a claim of pixel identity or exhaustive manual
inspection of every glyph.

Seven diagnostic regression tests pass, including page-aware whitespace
classification, detection of lost characters, ascent-based baseline
reconstruction, safe metric-experiment byte offsets, and explicit descriptor
errors and the clarified similarity acceptance criteria.
The extended nine-fixture qualification still passes exact text,
layout plans, deterministic hashes, and the 22 failure scenarios;
`--require-parity` now exits **0** after rechecking text, positions, and
300-DPI similarity on all fixtures.

**Next step after publication:** the main workflow qualifies the locally
accepted Cairo exporter in clean Ubuntu CI, then publishes its exports only
if that passes. The user's clarified
requirement resolves the earlier PDF-identity concerns; it does not eliminate
dependency, failure-mode, or reproducibility checks.
