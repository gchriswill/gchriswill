#!/usr/bin/env bash
# Check an exported RESUME.pdf against its README and RESUME.txt using poppler-utils.
# Usage: check-pdf.sh <directory containing README.md, RESUME.txt and RESUME.pdf>
set -euo pipefail

root=${1:?usage: check-pdf.sh <directory>}
pdf="$root/RESUME.pdf"
fail() { echo "check-pdf: $*" >&2; exit 1; }

info=$(pdfinfo "$pdf")
field() { sed -n "s/^$1:[[:space:]]*//p" <<<"$info"; }
digest=$(sha256sum "$root/README.md" | cut -d' ' -f1)
[[ $(field Title) == "Resume" ]] || fail "unexpected Title: $(field Title)"
[[ $(field Subject) == "README SHA-256: $digest" ]] || fail "Subject does not match README digest"
[[ $(field 'Page size') == "612 x 792 pts (letter)" ]] || fail "unexpected page size: $(field 'Page size')"
(( $(field Pages) >= 1 )) || fail "PDF has no pages"

pdffonts "$pdf" | grep -Eq 'DejaVuSansMono.*yes[[:space:]]+yes[[:space:]]+yes' \
  || fail "DejaVuSansMono is not embedded as a Unicode subset"

extracted=$(pdftotext -raw -enc UTF-8 "$pdf" -)
grep -q '<!-- resume:' <<<"$extracted" && fail "control markers appeared in the PDF"

# Every printable character of RESUME.txt must appear in order; wrapping only moves whitespace.
printable=$(grep -v -e '^<!-- resume:body:\(start\|end\) -->' -e '^<!-- resume:source:sha256 ' "$root/RESUME.txt")
squash() { tr -d '[:space:]\f' | sed 's/\xc2\xa0//g; s/\xe2\x80\x83//g'; }
[[ $(squash <<<"$extracted") == $(squash <<<"$printable") ]] \
  || fail "PDF text does not match RESUME.txt"

echo "check-pdf: $pdf OK ($(field Pages) pages)"
