# Markdown Resume Exporter

`MarkdownResumeExporter` is the Swift package in
[`scripts/markdown-resume-exporter`](./) that builds the `sync-resume` executable.

## Status: production

`sync-resume` generates [`RESUME.txt`](../../RESUME.txt) and
[`RESUME.pdf`](../../RESUME.pdf) from the resume section of
[`README.md`](../../README.md). It retains Pandoc, uses Apple's pinned
[swift-crypto](https://github.com/apple/swift-crypto) for SHA-256 (CryptoKit's
API, backed by bundled BoringSSL on Linux), and imports Cairo/FreeType
directly through SwiftPM system-library modules. There is no browser engine, custom PDF writer, or
silent renderer fallback.

The exporter was validated against the original Python generator on clean
Ubuntu CI (runs 38656343414 and 38656343482), and its exports were first
published to `main` in `d533ad9`. The Python generator, differential checker,
and PDF inspector were then retired. Their
outputs are preserved as frozen reference fixtures (see below), and they remain
available in Git history. To roll back, revert the migration commits.

The accepted contract is preserved text with very similar layout, not PDF byte
identity with the former ReportLab output.

## CI

Both workflows run on a fresh Ubuntu 24.04 runner and share the
[`setup-resume-build`](../../.github/actions/setup-resume-build/action.yml)
action. It installs the system dependencies, checks the exact DejaVu Sans Mono
hash, and installs Swift 6.3.2 from the official swift.org tarball only after
its pinned SHA-256 and release-signing-key signature are verified.

- [**Test RESUME exporter**](../../.github/workflows/test-resume.yml) runs
  read-only on pull requests, non-`main` pushes, and manual dispatch. It runs
  the Swift tests against the frozen reference fixtures, then compiles two
  independent clean release builds. Each exports a disposable copy of the
  README and text template, [`check-pdf.sh`](check-pdf.sh) validates each PDF,
  and the text/PDF hashes must match across builds.
- [**Sync RESUME**](../../.github/workflows/sync-resume.yml) runs on `main`
  pushes and manual dispatch. It runs the Swift tests, builds once, exports into
  the repository, runs [`check-pdf.sh`](check-pdf.sh), and commits
  `RESUME.txt` and `RESUME.pdf` only when they changed. Runs are serialized, and
  a newer `main` commit makes the push fail rather than overwrite newer content.

## Tests and frozen reference fixtures

[`Tests/ResumeCoreTests/Fixtures`](Tests/ResumeCoreTests/Fixtures) holds the
final output of the retired Python generator:

- `wrapping.json`: 1,565 wrapping cases (text, width, indent, expected lines).
- Eight end-to-end cases (LF, CRLF, outside-resume digest, Unicode aliases and
  combining marks, decomposed renderer Unicode, pagination, empty printable
  lines, nested headings). Each has a `README.md`, an input text template, the
  expected `RESUME.txt` bytes, and the expected line/page/baseline layout plan.

The fixtures are marked `-text` in [`.gitattributes`](../../.gitattributes) so
CRLF content is not normalized. Do not regenerate them from the Swift exporter;
change them only when the output contract intentionally changes, and review the
difference.

The Swift tests also cover deterministic regeneration, scratch cleanup, invalid
source/template markers, invalid UTF-8, missing fonts, and Pandoc that is missing,
fails, writes large stderr, or returns invalid JSON. They also cover PDF staging
directory and symlink failures, unwritable text, and text-first PDF replacement
failure. In every failure case the existing outputs must be unchanged.

[`check-pdf.sh`](check-pdf.sh) uses Poppler to require the `Resume` title, the
exact README digest subject, Letter pages, and an embedded Unicode DejaVu Sans
Mono subset. It also checks that the PDF text equals the printable `RESUME.txt`
text (ignoring whitespace) and that no control markers appear:

```sh
scripts/markdown-resume-exporter/check-pdf.sh "$PWD"
```

## Requirements

| Component | Tested version |
| --- | --- |
| Swift | 6.3.2 |
| swift-crypto | 5.0.1 (with swift-asn1 1.7.3), revisions pinned in [`Package.resolved`](Package.resolved) |
| Cairo | Ubuntu `1.18.0-3build1` |
| FreeType | Ubuntu `2.13.2+dfsg-1ubuntu0.2` |
| Pandoc | Ubuntu `3.1.3+ds-2` |
| Poppler (checks only) | Ubuntu `24.02.0-1ubuntu9.10` |
| DejaVu fonts | Ubuntu `2.37-8` |

The runtime dependencies are Pandoc, Cairo (1.16 or newer for PDF metadata),
FreeType, and the exact `/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf`
file with SHA-256
`c805f9436dbc268644c1d9584f01a601a653e028e08fd74b9b949f6cf8304d88`.
On Ubuntu, install `pkg-config`, `libcairo2-dev`, `libfreetype-dev`, `pandoc`,
`fonts-dejavu-core`, and `poppler-utils`.

## Local use

From the repository root:

```sh
swift test --package-path scripts/markdown-resume-exporter --force-resolved-versions
swift build -c release --package-path scripts/markdown-resume-exporter --force-resolved-versions
scripts/markdown-resume-exporter/.build/release/sync-resume --root "$PWD"
scripts/markdown-resume-exporter/check-pdf.sh "$PWD"
```

Repeating the export must leave the hashes unchanged. Normally, let the
production workflow publish exports on `main` instead of committing local ones.

The CLI is `sync-resume --root <dir> [--layout <json>] [--font <ttf>]`.
Invocation is independent of the caller's working directory. `--layout` writes
the exact line plan supplied to the renderer as sorted-key JSON. `--font`
supports failure tests.

### Repository-local dependencies

In this workspace, missing packages were extracted into the ignored
`.build-local/deps` directory instead of being installed system-wide:

```sh
export PATH="$PWD/.build-local/bin:$PWD/.build-local/deps/usr/bin:$PATH"
export LD_LIBRARY_PATH="$PWD/.build-local/deps/usr/lib/x86_64-linux-gnu"
export PKG_CONFIG_PATH="$PWD/.build-local/deps/usr/lib/x86_64-linux-gnu/pkgconfig:$PWD/.build-local/deps/usr/share/pkgconfig"
export PKG_CONFIG_SYSROOT_DIR="$PWD/.build-local/deps"
```

The ignored `.build-local/bin/pandoc` launcher supplies the relocated Pandoc
data directory. If Git's `safe.bareRepository=explicit` policy prevents SwiftPM
from resolving its bare dependency checkout, add
`GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.bareRepository GIT_CONFIG_VALUE_0=all`
to the Swift command. This does not modify Git configuration.

## Implemented contract

- Hash the entire README's exact bytes, including content outside the resume.
- Select one ordered pair of complete-line source/body markers; validate
  selected UTF-8 and reject empty source/conversion output.
- Preserve links recursively through a heterogeneous Codable Pandoc AST.
- Preserve source top-level ATX heading spacing, ignoring fences and rejecting
  heading mismatches or missing spacing sentinels.
- Preserve the text template's preamble/suffix bytes, body LF/CRLF convention,
  digest marker, and final-newline behavior.
- Wrap with the reference whitespace, tab-stop, Unicode scalar length,
  indentation, long-word, and disabled-hyphen-splitting rules.
- Derive wrapping columns from the unhinted font-unit `M` advance; render
  Letter pages at 9 points with 12-point baselines and 42-point margins.
- Retain blank lines and the inclusive bottom baseline at 42 points.
- Embed the exact font, reject missing glyphs/NUL, and draw with UTF-8 text
  clusters for selectable Unicode text.
- Keep the title, the exact digest subject, and invariant creation/modification dates.
- Keep native font resources alive through Cairo caches using a font-face
  destruction callback; check native statuses, including delayed write errors.
- Capture Pandoc stdout/stderr through workspace-local files, avoiding pipe
  deadlocks, and surface failures explicitly.

PDF staging comes first, then the text is published, then the PDF is replaced
with a POSIX rename. These are **non-atomic two-file** semantics: if the final
PDF replacement fails, the new text may already be published. The exporter
rejects a non-regular staging path, including a broken symlink, rather than
following it or deleting an existing directory.
