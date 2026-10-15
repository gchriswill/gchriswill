---
name: resume-profile-maintenance
description: "Use when maintaining or tailoring this repository's resume, professional bio, portfolio, cover letter, LinkedIn summary, or interview narrative. Ground every claim in the documented README resume."
---

# Resume and Profile Maintenance

Use this workflow for career materials based on the repository's resume.

## Sources and accuracy

1. Read the relevant sections of [`README.md`](../../../README.md), which is the canonical source of professional history.
2. Consult [`TIMELINE.md`](../../../TIMELINE.md) or [`PROGRESSION.md`](../../../PROGRESSION.md) only when chronology or career progression is relevant.
3. Preserve the distinction between completed work, current focus, and stated aspirations. Do not invent dates, titles, responsibilities, tools, metrics, or outcomes.
4. If a requested claim cannot be supported by these sources, leave it out or identify what needs confirmation.

## Tailoring

1. Identify the target role, audience, length, and requested format.
2. Select the most relevant documented experience and examples; prioritize the requested focus without overstating expertise.
3. Write clearly and specifically. Keep employer and project details accurate, and do not imply confidential or unpublished details beyond what the resume states.
4. Review the result against the source for factual accuracy, chronology, and consistency of terminology.

## Updating this repository

1. Change resume content only between `<!-- resume:start -->` and `<!-- resume:end -->` in README.
2. Preserve the markers and the existing Markdown structure. Keep Copilot guidance and repository documentation outside the resume markers.
3. Do not edit [`RESUME.txt`](../../../RESUME.txt) or [`RESUME.pdf`](../../../RESUME.pdf) directly. The [production workflow](../../workflows/sync-resume.yml) tests the Swift exporter and publishes its exports on main. For local regeneration, follow the [Swift exporter instructions](../../../scripts/swift-resume/README.md) and run `scripts/swift-resume/.build/release/sync-resume --root "$PWD"` from the repository root.
4. Verify the generated text and PDF reflect the change and that the README's source markers remain intact.
