# Goldfish Annotated Review Report

**Target:** `docs/designs/perturbation-study.md` (full file)
**Reviewers:** egm-zoom-out, egm-comprehension, egm-design, egm-structural
**Date:** 2026-10-27

## Prioritized Findings & AI Suggestions

### 1. The study is tautological: the claim contains the quote under test

* **Affected Scope:** Overview, Stage 1, Stage 2
* **Reviewer:** egm-design, egm-zoom-out, egm-structural
* **Discrepancy Description:** The claim sentence is chosen because it contains an
  eight-word verbatim run, and the quote recorded for scoring is that same run. The scoped
  check then string-matches the model's quote against the cited paragraph. On the clean arm
  the match is guaranteed; on a corrupted arm the absence is guaranteed. Catch approaches
  100% by construction and carries no information about a real brief, where drafters
  paraphrase.
* **AI Suggestion:** PROPOSE FIX
* **Justification:** A measurement that cannot fail is not a measurement. The verbatim
  case is worth reporting as the baseline the string check provides, but the claim that
  distinguishes Ruchi — support for a proposition that does not copy the judgment — must be
  tested with text that shares no long run with the paragraph.
* **Proposed Edit:** Split the study into two families on the same base items:
  **verbatim** (claim contains the run) and **paraphrase** (a restatement of the same
  sentence with no eight-word overlap, produced once by a model and hand-checked on 30
  items). Arms become clean / wrong paragraph / wrong judgment within each family. Report
  them apart; never pool.

### 2. `--review-policy` is unmeasured product surface

* **Affected Scope:** Goal 8, Stage 5, files 3, 4, 7, 8
* **Reviewer:** egm-zoom-out, egm-design
* **Discrepancy Description:** The flag moves the confidence floor, which only sets
  `needs_review`; support still stands. The study runs one policy and never compares them,
  so the sole user-facing change is shipped without evidence, against the document's own
  non-goal of user-facing change.
* **AI Suggestion:** PROPOSE FIX
* **Justification:** Every response already records the model's confidence. Sweeping the
  threshold inside `report` produces the same analysis with zero production code and zero
  unvalidated surface.
* **Proposed Edit:** Delete Goal 8 and Stage 5. Add to Stage 4: the report sweeps the
  recorded confidence to show the abstention/precision trade-off, and states that no
  product default changes. Remove `graph.py`, `scope.py`, `test_scope.py`, `test_cli.py`
  edits from the file list.

### 3. The voice arm's ground truth is not independent, and it is not within-subject

* **Affected Scope:** Stage 2, arm table
* **Reviewer:** egm-design, egm-structural
* **Discrepancy Description:** `paragraph.role` is assigned by `ingest/roles.py` using the
  same vocabulary ("learned counsel for the petitioners") that `attribute_voice` matches.
  The arm also takes its claim from a different paragraph, so it is a between-items
  comparison presented as a within-subject one, and voice is already measured on ten gold
  items.
* **AI Suggestion:** PROPOSE FIX
* **Justification:** One heuristic grading another is not validation, and the arm inflates
  the apparent breadth of the study while adding no independent evidence.
* **Proposed Edit:** Remove the voice arm from this study; move it to Future Improvements
  with the design it needs (quote-anchored role labels, hand adjudication of 20 items, a
  required `COURT_RESUMES_CUES` position check). The study drops to two families ×
  three arms.

### 4. Era and bench splits have no power and are confounded

* **Affected Scope:** Stage 1 quota, Stage 4 splits
* **Reviewer:** egm-structural, egm-design
* **Discrepancy Description:** Fifty items per 30-year band leaves one or two 1950s items,
  so the decade split is guaranteed to fall under the `n ≥ 10` rule and be suppressed.
  Quote length, paragraph count and printed-label form also drive catch and correlate with
  era, so the split reads text difficulty as defect difficulty.
* **AI Suggestion:** PROPOSE FIX
* **Justification:** An analysis that is guaranteed to be suppressed should not be in the
  design; a confounded split should not be published.
* **Proposed Edit:** Quota 25 per decade (200 total). Record era, quote length, paragraph
  count and bench strength per item as covariates. Report no split unless `n ≥ 10`, and
  state that none of them is powered.

### 5. The clean arm can pass a phantom citation

* **Affected Scope:** Stage 4, outcome taxonomy
* **Reviewer:** egm-comprehension, egm-structural
* **Discrepancy Description:** `pass` is defined as "no pointer finding", so a mode 1
  phantom — the judgment not resolving at all — would count as a clean pass.
* **AI Suggestion:** PROPOSE FIX
* **Justification:** The guardrail exists to catch false alarms; it must also refuse to
  count a resolution failure as silence.
* **Proposed Edit:** `pass` requires `existence == found`; mode 1 becomes `wrong_flag`.

### 6. Denominators, precedence and "200 items each" are undefined

* **Affected Scope:** Stage 2, Stage 4, Goal 2
* **Reviewer:** egm-comprehension, egm-structural
* **Discrepancy Description:** `all` is never defined; arm construction drops items, so
  "200 items each" cannot be true; the ordering of error / caught / abstain / not_caught is
  unstated; and `caught` requiring the exact expected mode scores a correct detection under
  a neighbouring mode as a miss.
* **AI Suggestion:** PROPOSE FIX
* **Justification:** Without these three definitions the table cannot be audited.
* **Proposed Edit:** Define `all = caught + not_caught + abstain + error`; precedence
  `error > caught > abstain > not_caught`; primary `caught` is any pointer finding (modes
  1, 2, 3, 4, 12), with exact-mode agreement as a secondary column. Report constructed
  counts and drop reasons per arm.

### 7. The cited-page comparison to published numbers is illegible

* **Affected Scope:** The Problem, Stage 4
* **Reviewer:** egm-design, egm-zoom-out
* **Discrepancy Description:** 93–100% and 37–61% are all-in rates over fourteen
  configurations, US opinions and briefs, with page-level pinpoints; Ruchi would report
  decided-only catch on Indian paragraphs. The source paper also reports that asking a model
  to verify at the page raises false positives, a trade the design does not engage.
* **AI Suggestion:** PROPOSE FIX
* **Justification:** Two numbers in one table invite a comparison the protocols do not
  support.
* **Proposed Edit:** Name the source paper and its protocol in one sentence; state that the
  study compares mechanisms, not scores; print the published bands in prose, never in the
  same table as Ruchi's numbers.

### 8. The OCR "fix" cannot work and would invalidate the sample

* **Affected Scope:** Stage 1 filter, "The OCR check", file 5, Rollback NFR
* **Reviewer:** egm-comprehension, egm-design, egm-structural
* **Discrepancy Description:** `store.py` affects future ingests only; 707,647 stored
  paragraphs would keep a false flag. `graph.scope_node` never passes `ocr_derived` into
  `assess_scope`, so before/after rates would be identical. Re-ingesting before the deadline
  changes the corpus hash and every frozen item.
* **AI Suggestion:** PROPOSE FIX
* **Justification:** A change that cannot affect the measurement is not a fix; a corpus
  rebuild inside the deadline is a risk with no matching benefit.
* **Proposed Edit:** Keep the 60-paragraph check as a diagnostic only. Report it as a
  limitation with its own count. Delete file 5 and the claim that the flag will be derived.

### 9. Interviews are a second deliverable with no fallback

* **Affected Scope:** Goal 7, file 11, acceptance criteria
* **Reviewer:** egm-zoom-out, egm-design
* **Discrepancy Description:** "Four transcripts" as an acceptance criterion makes the study
  hostage to recruitment, and the interview work is already owned by ROADMAP WBS 7.2.
* **AI Suggestion:** PROPOSE FIX
* **Justification:** Two deliverables with one deadline means one of them slips silently.
* **Proposed Edit:** Move the protocol and coding sheet to `docs/research/interviews/` as
  their own task, referenced but not required by this design. Remove transcripts from the
  acceptance list.

### 10. Cost is understated and concurrency is unstated

* **Affected Scope:** NFR, cost
* **Reviewer:** egm-design
* **Discrepancy Description:** 1,000 arm items at up to four calls each, 6–10 seconds per
  call, is 6.7–11 hours serial, not 3–4.
* **AI Suggestion:** PROPOSE FIX
* **Justification:** The batch must finish inside a working day, and a serial run does not.
* **Proposed Edit:** State four workers, roughly 2–3 hours, with the pilot measuring the
  real rate; keep the cost estimate as "tens of dollars".

### 11. Confounds are unrecorded

* **Affected Scope:** Stage 1, Stage 3
* **Reviewer:** egm-structural
* **Discrepancy Description:** Quote length, number of paragraphs in the cited judgment,
  and printed-label form all drive catch. None is recorded, so no arm can be adjusted for
  them.
* **AI Suggestion:** PROPOSE FIX
* **Justification:** A reader who suspects length effects cannot check.
* **Proposed Edit:** Record all three per item in `items.jsonl` and report their
  distribution per arm.

### 12. The replay schema names no keys

* **Affected Scope:** Stage 3
* **Reviewer:** egm-comprehension
* **Discrepancy Description:** "The verdict fields used in scoring" cannot be rebuilt into
  a table.
* **AI Suggestion:** PROPOSE FIX
* **Justification:** The offline replay gate is only meaningful if the row is specified.
* **Proposed Edit:** Rows record `item_id`, `arm`, `model_id`, `prompt_versions`,
  `existence`, `support`, `quote_verified`, `quote_match_type`, `needs_review`,
  `confidence`, `findings[{mode,label}]`, `seconds`, `error`.

### 13. No Risks and Mitigations section

* **Affected Scope:** whole document
* **Reviewer:** egm-design
* **Discrepancy Description:** The design lists open questions but no threats and no
  responses.
* **AI Suggestion:** PROPOSE FIX
* **Justification:** The capstone report needs one; the implementation needs it more.
* **Proposed Edit:** Add a four-row section: paraphrase drift, item clustering, provider
  nondeterminism, deadline slip.

### 14. File list carries artifacts that do not belong to the build

* **Affected Scope:** Detailed Implementation Plan, files 9, 12, 13
* **Reviewer:** egm-zoom-out
* **Discrepancy Description:** File 12 lists the design as its own deliverable; file 13
  edits a document built by a script living outside the repository; file 9 defines three
  output formats for one table.
* **AI Suggestion:** PROPOSE FIX
* **Justification:** The plan should name what an implementer builds, not the paperwork that
  follows.
* **Proposed Edit:** Delete file 12. Move file 13 to a follow-up note and bring the docx
  build script into `scripts/` when it is regenerated. Collapse file 9 to `items.jsonl`,
  `manifest.json`, `responses.jsonl`, `summary.json` and one `table.txt` in the shape the
  other evaluators already use.

### 15. Sampling direction is stated backwards

* **Affected Scope:** Stage 1, step 3
* **Reviewer:** egm-comprehension
* **Discrepancy Description:** The text builds shingles from the citing paragraph and
  searches the cited judgment; it should be the reverse, so the matched paragraph is
  known to be in the citing judgment.
* **AI Suggestion:** PROPOSE FIX
* **Justification:** Either direction finds the same shared run, but only the stated one
  guarantees where the claim sentence lives.
* **Proposed Edit:** Take shingles from the cited paragraph, search the citing judgment,
  and take the claim from the paragraph that matched.

### 16. Docx regeneration depends on a scratch script

* **Affected Scope:** file 13
* **Reviewer:** egm-zoom-out
* **Discrepancy Description:** The addendum is generated by
  `A:\Order\data\tmp\build_addendum.py`, outside the repository, so nobody else can rebuild
  it.
* **AI Suggestion:** CONTEST (partially)
* **Justification:** The script is scratch by choice: it holds absolute paths for this
  machine. Moving it into the repository is right, but it should happen when the addendum
  is regenerated, not as part of this study.
* **Proposed Edit:** Note in Future Improvements that the build script moves to `scripts/`
  at the next regeneration.

## Status

resolved — 16 findings; 15 proposed fixes applied to `docs/designs/perturbation-study.md` (v2), 1 contested (the docx build script stays outside the tree until the next regeneration)
