---
name: resume-profile-maintenance
description: "Use when maintaining or tailoring this repository's resume, professional bio, portfolio, cover letter, LinkedIn summary, interview narrative, or career timeline and Mermaid GitGraph. Ground professional claims in the documented README resume and detailed chronology in TIMELINE.md."
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
3. Do not edit [`RESUME.txt`](../../../RESUME.txt) or [`RESUME.pdf`](../../../RESUME.pdf) directly. The [production workflow](../../workflows/sync-resume.yml) tests the Swift exporter and publishes its exports on main. For local regeneration, follow the [Swift exporter instructions](../../../scripts/markdown-resume-exporter/README.md) and run `scripts/markdown-resume-exporter/.build/release/sync-resume --root "$PWD"` from the repository root.
4. Verify the generated text and PDF reflect the change and that the README's source markers remain intact.

## Maintaining the career timeline

1. Read both the Mermaid graph and the text chronology in [`TIMELINE.md`](../../../TIMELINE.md) before editing. Preserve user corrections, and keep dates and event order consistent between the two representations. Do not change unrelated chronology or infer missing dates.
2. Use a single top-to-bottom Mermaid `gitGraph` with `Self` as the main branch. Set explicit branch orders: Certifications (1), Education (2), Volunteering (3), Projects (4), Career (5).
3. Classify events consistently:
   - Certifications: earned professional certifications and training credentials, plus their expiry events.
   - Education: degrees, academic certificates, and explicitly started/completed courses. The Boston University graduate certificate and Microsoft Learn GitHub Foundations course remain here; the GitHub Foundations certification belongs on Certifications.
   - Volunteering: volunteer roles and related awards.
   - Projects: applications, services, and technical contributions, including employer projects.
   - Career: employment roles and promotions, not their associated projects.
4. Represent each start as a `Start:` commit on its category branch and each completion as a `Done:` merge from that branch into `Self`. Do not also add a Done commit on the source branch. Keep promotions, awards, and expiry events distinct from completions.
5. The existing same-month Start/Done pairs for earned credentials are a visualization convention when only an earned date is documented. They do not establish a factual study start date; never use them as evidence of one in professional materials.
6. Keep labels descriptive enough to identify the role, institution, credential, or project. Retain horizontal commit labels (`rotateCommitLabel: false`); avoid arbitrary character limits or excessive abbreviations. Preserve the current theme and font settings unless a requested change or rendered overlap warrants adjusting them.
7. Validate unique event IDs, `YYYY-MM` tags, chronological order (including the text's ordering within a month), category assignments, and completion merges into `Self`. Check that merge source and destination heads differ. Render graph changes with an available Mermaid renderer and inspect affected sections for overlap and clipping; report any rendering limitation rather than claiming visual verification.
