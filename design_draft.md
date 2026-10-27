# Perturbation study: measuring whether Ruchi catches a broken citation

* **Author:** Afjal Hussein (S24BCAU0171)
* **Status:** Draft
* **Date:** 2026-10-27

--------------------------------------------------------------------------------

## Overview

Ruchi verifies citations in an Indian legal brief against a local corpus of 38,032
Supreme Court judgments. It reports whether a citation exists, whether the paragraph it
names contains the quoted words, whose voice the passage carries, how far the passage
supports the proposition, and whether later judgments have damaged it.

The engine reports a support grade on every citation. The evaluation set cannot score it:
`support` is labelled in none of the 70 gold items and 39 of the 313 holdout items; `weight`
and `applicability` are labelled in neither. The only failure mode with a published
external measurement — a real case cited for a proposition it does not support at the
pinpoint given — is the one this project is least able to demonstrate.

This design adds a perturbation study: real citations from the corpus, each broken in one
known way, measured on whether the engine notices. It changes no user-facing behaviour
except one opt-in operating point.

## The Problem

Three problems, one solution.

**The project cannot answer "how do you know it works".** Every accuracy number in the
report comes from 70 synthetic items in which the distinguishing check is unlabelled.
A panel, an examiner or a reader can falsify the claim by reading `evals/gold.jsonl`.

**The field says the hard part is support, not existence.** *Is this Citation on Point?*
(arXiv:2608.12571) measures proposition-level support by perturbing real citations and finds
wrong-case detection at 93–100% but wrong-pinpoint detection at 37–61%. *When Citations
Mislead?* (PARCEL, arXiv:2610.10971) finds models over-accept unsupported claims even with
the full opinion in context. Ruchi's mechanism — make the model produce a quote, then
string-match that quote against the stored paragraph — is a direct answer to the failure
both papers describe, and it has never been measured.

**Annotation is not affordable before 09 November.** Hand-labelling support across 313
items at the quality bar of PARCEL is weeks of legal reading. Perturbation produces ground
truth by construction instead: if the quote was taken from paragraph 7 of judgment A, then
a citation to paragraph 9 of judgment A is wrong, and no lawyer has to be asked.

## Goals

1. **A frozen sample of 200 base citations**, reproducible byte-for-byte from a seed, with a
   manifest recording corpus hash, repository commit, model id, region, prompt versions,
   sampling query and `top_k`.
2. **Five arms, 200 items each, within-subject**: clean pointer, wrong judgment, wrong
   paragraph, adjacent paragraph, counsel-attributed-to-court.
3. **A results table** with, per arm: decided-only catch (primary), all-in catch,
   abstention, and the count in each of four outcomes. Wilson 95% intervals on every rate.
   Decade and bench size reported descriptively, and only for cells with n ≥ 10.
4. **A false-alarm guardrail**: on the clean arm, pointer findings must be ≤ 5%, with the
   upper bound of the interval reported even when the point estimate is zero.
5. **Offline reproducibility**: `orderorder eval perturb report` regenerates every number
   in the table from a response cache, with no network call and no model.
6. **Evidence for the OCR question**: 60 paragraphs across three decades, checked by hand
   against their source text, so that quote verification failures are attributed to the
   engine and not to unmarked OCR noise.
7. **Interview evidence**: a four-question kit, four transcripts, and a coding sheet for
   three users and one faculty member, collected in the first week and reported as
   formative.
8. **One visible change**: an opt-in operating point on `verify` that selects a strict or a
   recall-seeking review policy, so the study produces a product delta and not only a table.

## Non-Goals

* No new failure mode, check, or detector.
* No change to the default verdict behaviour, grading rubric or report format.
* The overstatement arm (mode 8) is excluded: it fires only when the model answers
  "partial", so a "full" answer produces no finding and the arm would measure model
  caution, not verification. It moves to Future Improvements.
* Hand-labelling `support` across the 313-item holdout.
* Hindi or other Indian-language text, High Court judgments, or corpus expansion.
* "Here is the authority that does support you" — the practitioner follow-up, not this study.
* Any hosted service, dashboard, or web surface for the results.

## Open Questions

* **Q1 — Does `citation_edge.paragraph_id` point at the citing paragraph?** The sampling
  plan joins citing paragraph to cited judgment. If the column is null or unreliable for
  most edges, the fallback is a full-text search for the quoted run inside the citing
  judgment. To be settled by a 20-edge inspection before the sampler is written.
* **Q2 — Is the OCR flag genuinely wrong?** `ingest/store.py` sets `ocr_derived=False` for
  every text version. If the 60-paragraph check finds that older text is OCR output, the
  flag must be derived at ingest and the study reports rates before and after.
* **Q3 — Do adjacent paragraphs often contain the same quote?** If they do, the adjacent arm
  has no clean ground truth and those items are dropped. Settled by adjudicating 30.
* **Q4 — Is the model deterministic enough at temperature 0?** Ten per cent of items are run
  twice and the disagreement rate is reported; the cache stores the first response used.
* **Q5 — What is the wall-clock cost per item?** One verification can call up to four model
  nodes. Measured on 20 items before the full run; if it exceeds 20 seconds, the model arms
  use 120 items and the protocol says so.

## Critical User Journeys (CUJs)

### CUJ 1: Reproducing the sample

* **Given**: a clean checkout and `ORDERORDER_DATA_DIR` pointing at the corpus.
* **When**: `orderorder eval perturb sample --n 200 --seed 42` runs twice.
* **Then**: both runs write the same item ids, the same quoted spans, and the same
  `sha256` in the manifest. A manifest mismatch is a failure, not a warning.

### CUJ 2: Running the arms without losing work

* **Given**: a frozen sample and a pinned model.
* **When**: `orderorder eval perturb run --arm wrong_paragraph` is interrupted and restarted.
* **Then**: completed items are skipped by id, the response cache grows, and the run
  resumes without re-billing completed calls. Every item records the model id that answered.

### CUJ 3: Checking a number at the viva

* **Given**: a finished run.
* **When**: a reader asks where "decided-only catch 71%" comes from.
* **Then**: `orderorder eval perturb report --arm wrong_paragraph --detail` prints the
  numerator, denominator, interval, and one worked item: claim, citation given, where the
  quote actually lives, which mode fired.

### CUJ 4: An interview

* **Given**: an advocate or student and their own brief.
* **When**: they run `orderorder verify --file <their brief>` with the researcher present,
  then answer four questions.
* **Then**: the transcript records what they expected, what surprised them, which finding
  they would act on first, and what would make them stop using it. Coded into themes
  within a week.
