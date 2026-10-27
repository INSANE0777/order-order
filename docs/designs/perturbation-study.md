# Perturbation study: measuring whether Ruchi catches a citation that does not hold

* **Author:** Afjal Hussein (S24BCAU0171)
* **Status:** Proposed
* **Date:** 2026-10-27
* **Revision:** v2, after four-lens Goldfish review (`goldfish_review_report.md`)

--------------------------------------------------------------------------------

## Overview

Ruchi verifies citations in an Indian legal brief against a local corpus of 38,032
Supreme Court judgments. It reports whether a citation exists, whether the paragraph it
names contains the quoted words, whose voice the passage carries, how far the passage
supports the proposition, and whether later judgments have damaged it.

The engine reports a support grade on every citation. The evaluation set cannot score it:
`support` is labelled in none of the 70 gold items and 39 of the 313 holdout items; `weight`
and `applicability` are labelled in neither. The failure mode with a published external
measurement — a real case cited for a proposition it does not support at the pinpoint given
— is the one this project is least able to demonstrate.

This design adds a perturbation study: real citations from the corpus, each broken in one
known way, measured on whether the engine notices. It changes no user-facing behaviour, no
schema and no default. It adds one command and one data directory.

**Two families, because quotation and paraphrase are different problems.** When a brief
copies a run of words from the judgment, a string check settles it. When a brief restates
the holding in its own words, only a reading of the paragraph can settle it — and that is
the case the field calls unsolved. The study measures both, reports them apart, and never
pools them.

## The Problem

Three problems, one solution.

**The project cannot answer "how do you know it works".** Every accuracy number in the
report comes from 70 synthetic items in which the distinguishing check is unlabelled. A
panel, an examiner or a reader can falsify the claim by reading `evals/gold.jsonl`.

**The field says the hard part is support, not existence.** *Is this Citation on Point?*
(arXiv:2608.12571) perturbs real US citations and finds wrong-case detection at 93–100% but
wrong-pinpoint detection at 37–61%; it also finds that asking a model to verify at the
cited page raises the false-positive rate. *When Citations Mislead?* (PARCEL,
arXiv:2610.10971) finds models over-accept unsupported claims even with the full opinion in
context. Both describe a failure this project claims to address and has never measured.

**Annotation is not affordable before 09 November.** Hand-labelling support across 313
items at PARCEL's quality bar is weeks of legal reading. Perturbation produces ground truth
by construction: if the sentence was taken from paragraph 7 of judgment A, a citation to
paragraph 9 of judgment A is wrong, and no lawyer has to be asked.

**What the study can and cannot claim.** It compares mechanisms, not scores. The published
bands come from US opinions and briefs, page-level pinpoints, fourteen model
configurations and all-in rates. This study uses one model, Indian paragraphs, its own
sampling frame and decided-only rates. The report names the source and the difference in
the same sentence; it never puts the two sets of numbers in one table.

## Goals

1. **A frozen sample of 200 base items**, 25 per decade of the cited judgment, reproducible
   byte-for-byte from a seed, with a manifest recording corpus hash, repository commit,
   model id, region, prompt versions, sampling query and `top_k`.
2. **Two families × three arms, within-subject**: verbatim {clean, wrong paragraph, wrong
   judgment} and paraphrase {clean, wrong paragraph, wrong judgment}. 1,200 arm items in
   total, with construction counts and drop reasons published per arm.
3. **A results table** with, per arm: decided-only catch (primary), all-in catch,
   abstention, error count, and the count in each outcome. Wilson 95% intervals everywhere,
   including on a zero count.
4. **A false-alarm guardrail**: on both clean arms, pointer findings at or below 5%, with
   the upper interval bound reported. `pass` requires that the judgment resolved.
5. **Offline replay**: `orderorder eval perturb report` rebuilds every number from
   `responses.jsonl` with no network call and no model.
6. **A confidence sweep**: the report replays the recorded model confidence at three
   thresholds and prints the precision/abstention trade-off, so the study states the cost
   of its operating point without changing the product's.
7. **A paraphrase check**: 30 paraphrased items hand-compared with their source sentence,
   agreement reported, and the failure rate of paraphrase generation stated.
8. **An OCR diagnostic**: 60 paragraphs across three bands checked by hand against their
   source, reported as a limitation with its own count. No ingestion change.

**Primary endpoint, fixed before the run:** decided-only catch on the paraphrase
wrong-paragraph arm — `caught / (caught + not_caught)`. Everything else is secondary.

## Non-Goals

* No new failure mode, check, or detector.
* No change to verdict behaviour, grading rubric, review thresholds, output formats or the
  default configuration. The confidence sweep is analysis, not a switch.
* No change to ingestion, and no corpus rebuild. `ocr_derived` stays as it is; the
  diagnostic reports what that costs.
* The voice arm is excluded: `paragraph.role` is assigned by regex cues that share
  vocabulary with `attribute_voice`, so the arm would grade one heuristic with another. It
  moves to Future Improvements with the design it needs.
* Hindi or other Indian-language text, High Court judgments, or corpus expansion.
* Hand-labelling `support` across the 313-item holdout.
* "Here is the authority that does support you" — the practitioner follow-up.
* Interviews. The four-question kit and coding sheet live in
  `docs/research/interviews/` as their own task under ROADMAP WBS 7.2; this study does not
  depend on them and does not fail without them.

## Open Questions

* **Q1 — answered, and it changed the sampler.** `citation_edge.paragraph_id` is populated
  for all 64,828 edges but frequently points at a citation index rather than the citing
  sentence. Four sampled edges resolved to one paragraph whose text is "We have heard
  learned counsel for the parties … 5 2007 INSC 496 : (2007) 6 SCC 162 …". The citing
  sentence is therefore located by searching the citing judgment for a run taken from the
  cited paragraph. `paragraph_id` is a hint only.
* **Q2 — How often does paraphrase generation drift from the source sentence?** Measured on
  the 30-item check. If more than one in five drifts, the paraphrase family is reported as
  exploratory and the primary endpoint moves to the verbatim wrong-paragraph arm before the
  full run.
* **Q3 — Do adjacent paragraphs contain the quote often enough to empty the arm?** The
  adjacent arm is dropped; wrong paragraph requires a gap of at least two positions and
  excludes any paragraph containing the quote. The exclusion count is reported; if it
  exceeds a third of candidates, the arm reports the reason.
* **Q4 — Is the model deterministic enough at temperature zero?** Ten per cent of items run
  twice; disagreement is reported; the cache keeps the first response.
* **Q5 — What is the wall-clock cost per item?** Measured on 20 items before the batch with
  four workers. If it exceeds 25 seconds per item, the batch is 150 items per arm and the
  protocol says so before the run, not after.

## Critical User Journeys (CUJs)

### CUJ 1: Reproducing the sample

* **Given**: a clean checkout and `ORDERORDER_DATA_DIR` pointing at the corpus.
* **When**: `orderorder eval perturb sample --per-decade 25 --seed 20261027` runs twice.
* **Then**: both runs write the same item ids, the same spans and the same `sha256` in the
  manifest. A mismatch is a failure.

### CUJ 2: Running the arms without losing work

* **Given**: a frozen sample and a pinned model.
* **When**: `orderorder eval perturb run --arm paraphrase_wrong_paragraph` is interrupted
  and restarted.
* **Then**: completed items are skipped, the cache grows, and no completed call is repeated.
  Every row records the model id that answered.

### CUJ 3: Checking a number at the viva

* **Given**: a finished run.
* **When**: a reader asks where "decided-only catch 61%" comes from.
* **Then**: `report --arm paraphrase_wrong_paragraph --detail` prints numerator, denominator,
  interval, drop counts and one worked item: claim, citation given, where the source
  sentence lives, which modes fired.

--------------------------------------------------------------------------------

## Technical Plan (Architecture)

The study is a batch job with a frozen input and a replayable output. It calls the same
`verify_citation` a brief calls and records what came back.

```text
  corpus (SQLite)
      |
      |  sample: shingle search from cited paragraph into citing judgment
      v
  items.jsonl  +  manifest.json          (frozen, committed)
      |
      |  paraphrase: one model call per base item, stored, overlap-checked
      v
  paraphrases.jsonl
      |
      |  arms: three per family, deterministic construction
      v
  arm items (6 per base item)
      |
      |  run: verify_citation, one pinned model, four workers, cache
      v
  responses.jsonl                        (resumable)
      |
      |  score: outcomes, intervals, confidence sweep
      v
  summary.json  +  table.txt             (rebuildable offline)
```

### Stage 1 — sampling the base items

1. Start from `citation_edge` where `cited_id` is not null — all 64,828 rows qualify.
2. Take eight-word shingles from each paragraph of the **cited** judgment and search the
   **citing** judgment with `paragraph_fts` (which stores `judgment_id` as an unindexed
   column, so the search is filtered, not indexed twice).
3. The longest match gives the source paragraph in the cited judgment and the citing
   paragraph that reproduces it. The claim sentence is the citing sentence containing the
   run; the quote is the run itself with offsets inside the cited paragraph.
4. Record: citing key, citing paragraph id, cited key, cited paragraph id and
   `printed_label`, quote text and offsets, claim sentence, `citation_raw` and its span,
   era, bench strength, quote length in words, paragraph count of the cited judgment, and
   whether the label is numeric.

Filters, each counted in the manifest:

* run of at least eight words, quote of at least twelve;
* claim sentence between 40 and 400 characters;
* the citing sentence names exactly one judgment;
* at most two items per citing judgment;
* the cited text version is not `ocr_derived`.

Quota: **25 per decade**, 200 in total. The corpus holds 1,004 judgments from the 1950s and
4,806 from the 2020s; the quota is a sampling choice, not a supply limit.

### Stage 2 — the paraphrase family

For each base item, one model call rewrites the claim sentence so that it carries the same
proposition and shares no eight-word run with the source paragraph. The paraphrase is
stored; it is never generated during scoring, so the table can be rebuilt without a model.

Checks applied at generation time, recorded per item:

* longest shared word run with the source paragraph is under eight;
* length between 40 and 400 characters;
* the paraphrase does not name a different judgment.

Thirty items are hand-compared with their source sentence and the drift count is reported.
A paraphrase that fails a check is regenerated once, then dropped with a reason.

### Stage 3 — the six arms

| family | arm | construction | expected |
|---|---|---|---|
| verbatim | clean | cite the paragraph the run lives in | pass |
| verbatim | wrong_paragraph | same judgment, paragraph at least two positions away, not containing the run | 12 or 4 |
| verbatim | wrong_judgment | different judgment in the same decade, BM25 rank 20–100, not containing the run | 2 or 4 |
| paraphrase | clean | correct paragraph, paraphrased claim | pass |
| paraphrase | wrong_paragraph | same judgment, paragraph at least two positions away | 12 or 4 |
| paraphrase | wrong_judgment | different judgment, same decade, BM25 rank 20–100 | 2 or 4 |

The BM25 rank band is stated so the distractor is neither trivially unrelated nor a near
duplicate. Rank and score are recorded per item. Constructions that fail a check are
dropped, not repaired, and the drop reason is counted per arm.

### Stage 4 — running

`verify_citation(session, citation, proposition, model, top_k=6, voice_model=…,
weight_model=…)` with a model built from a single explicit provider spec, so the fallback
chain cannot answer one item and resume on another. Four workers, one JSON line per item
written as it completes:

`item_id, arm, model_id, prompt_versions, existence, support, quote_verified,
quote_match_type, needs_review, confidence, findings[{mode,label}], seconds, error`

Restarting skips ids whose row has no error. A response cache keyed by
`sha256(item_id + arm + prompt_version_set + model_id)` makes a second run free. A swallowed
provider exception is recorded as `node_error` and scored `abstain`, not `caught`.

Twenty items are run twice before the batch to measure cost and disagreement.

### Stage 5 — scoring

Outcomes per item, with precedence `error > caught > abstain > not_caught`:

* **clean arms**: `pass` (existence found, no pointer finding), `wrong_flag` (a pointer
  finding, including mode 1), `abstain`, `error`.
* **corrupted arms**: `caught` (any pointer finding: modes 1, 2, 3, 4, 12), `not_caught`
  (a verdict was reached and no pointer finding fired), `abstain`, `error`.

Denominators: `all = caught + not_caught + abstain + error` per arm, using the constructed
count, which is published next to the intended count. False-alarm rate is
`wrong_flag / (pass + wrong_flag)` on each clean arm.

Reported: decided-only catch, all-in catch, abstention, error count, interval. Exact-mode
agreement is a secondary column, not the definition of caught. The confidence sweep replays
the recorded confidence at 0.15 / 0.35 / 0.60 and prints what each would have decided.

No rate is pooled across arms or families. There is no single accuracy number for the study.

### The OCR diagnostic

Sixty paragraphs — twenty each from 1950–79, 1980–99 and 2000–25 — are compared by hand
with their source and marked OCR or digital. The count is reported in the limitations
section beside every quote-verification rate, because `graph.scope_node` never passes an OCR
flag into `assess_scope` and stored flags cannot be corrected without re-ingesting. No code
changes as a result.

## Alternatives Considered

### Alternative A: label support across the 313-item holdout

* **Pros**: measures the check directly on human judgement; no new harness.
* **Cons**: weeks of legal reading at PARCEL's quality bar; single annotator, no drift check.
* **Reason for Rejection**: it does not fit before 09 November and would make one person's
  reading the weakest link.

### Alternative B: generate more synthetic items with the existing generator

* **Pros**: `evaluation/generate.py` exists.
* **Cons**: the generator writes claims that share wording with the chosen paragraph, so
  item and ground truth come from the same text.
* **Reason for Rejection**: a larger synthetic set makes the numbers larger, not truer.

### Alternative C: ask a model to judge support, and score the judge

* **Pros**: covers paraphrase without perturbation.
* **Cons**: PARCEL shows models over-accept unsupported claims with the full text in view.
* **Reason for Rejection**: circular, and contradicted by the 2026 evidence.

### Alternative D: replicate a published benchmark directly

* **Pros**: comparability.
* **Cons**: the 2026 benchmarks are US corpora; no Indian equivalent exists.
* **Reason for Rejection**: it would compare jurisdictions, not mechanisms.

### Alternative E: keep the voice arm

* **Pros**: mode 5 is a real failure and a differentiator.
* **Cons**: its ground truth (`paragraph.role`) is produced by the same cue vocabulary as
  `attribute_voice`, and the arm is not within-subject.
* **Reason for Rejection**: one heuristic cannot validate another. Moved to Future
  Improvements with a quote-anchored label and hand adjudication.

### Alternative F: ship a review-policy flag as the product delta

* **Pros**: gives the panel something new to click.
* **Cons**: the flag moves only `needs_review`; the study never varies it, so it would ship
  unmeasured, and the document's own non-goal is no user-facing change.
* **Reason for Rejection**: the confidence sweep delivers the same analysis with no new
  surface and no unvalidated default.

--------------------------------------------------------------------------------

## Non-Functional Requirements

* **Cost and throughput**: 1,200 arm items plus 200 paraphrase calls, up to four model calls
  per item, at 6–10 seconds per call. Four workers put the batch at roughly 2–3 hours and
  tens of dollars at Bedrock on-demand prices. The 20-item pilot measures the real figure and
  fixes the batch size before the run.
* **Determinism**: seeded sample with a hashed manifest, cached model responses, model id and
  prompt versions per row. A table that cannot be rebuilt from the cache is a failed run.
* **Privacy**: judgment text is public, CC-BY-4.0. No user brief enters the study.
* **Rollback**: the study adds one command and one data directory. Deleting either restores
  current behaviour; there is no schema, migration, threshold or default to revert.
* **Failure isolation**: a provider error marks one item `node_error`; it never aborts the
  batch and is reported as its own count per arm.

## Risks and Mitigations

| risk | consequence | mitigation |
|---|---|---|
| Paraphrase drifts from the source sentence | ground truth is wrong and the arm is meaningless | 30-item hand check; drift above one in five moves the primary endpoint to the verbatim arm before the run |
| Items cluster by citing judgment | intervals are too narrow | at most two items per citing judgment; clustering stated beside every interval |
| Provider answers differently across runs | table is not reproducible | one pinned model, no fallbacks, cache, 10% repeat and disagreement reported |
| Provider error swallowed as "needs review" | a silent error looks like caution | `node_error` recorded and counted separately; scored as abstention |
| Deadline slip | half a table at the viva | fixed 150-per-arm fallback decided at the pilot, written into the protocol before the run |
| Result is unflattering | the paraphrase arm may show the engine is weak | the protocol commits to publishing the number as measured, in the same table shape |

--------------------------------------------------------------------------------

## Detailed Implementation Plan

### Target Files to Create/Modify

#### 1. `src/orderorder/evaluation/perturb.py` (Create)

* **Type / Scope**: Python module, ~450 lines.
* **Proposed Changes**: sampling (`sample_base_items`), paraphrase generation and checks
  (`make_paraphrases`), arm construction (`build_arms`), outcome classification
  (`classify`), Wilson intervals (`wilson`), summarisation with `n ≥ 10` suppression
  (`summarise`), and the batch runner with cache and resume (`run_arms`).

#### 2. `src/orderorder/cli.py` (Modify)

* **Type / Scope**: CLI, existing `eval_app` group.
* **Proposed Changes**: `eval perturb sample|paraphrase|run|report|show` with the flags named
  in the CUJs. No change to `verify` and no change to any default.

#### 3. `tests/test_perturb.py` (Create)

* **Type / Scope**: Unit tests, no network, no corpus file.
* **Proposed Changes**: sampling direction and shingle floor; each filter rejecting its
  case; paraphrase overlap check at seven and eight words; determinism from a seed; drop
  reasons counted; outcome precedence; `pass` refusing a phantom; any-pointer-mode catch;
  abstention outside the decided-only denominator; Wilson bounds at n = 0, 1, 25, 200;
  suppression below n = 10; manifest hash stable; replay from a fixture cache with no keys
  present.

#### 4. `evals/perturb/` (Create)

* **Type / Scope**: Committed data and outputs.
* **Proposed Changes**: `items.jsonl`, `manifest.json`, `paraphrases.jsonl`,
  `responses.jsonl`, `summary.json`, `table.txt`, and `README.md` naming the command that
  reproduces each file and the corpus hash it was built against.

#### 5. `docs/research/perturbation-protocol.md` (Create)

* **Type / Scope**: Pre-registration.
* **Proposed Changes**: arms, outcomes, denominators, primary endpoint, drop rules,
  confidence sweep values, batch size, and the date — committed before the first full run.

#### 6. `docs/research/interviews/` (Create)

* **Type / Scope**: Separate task under ROADMAP WBS 7.2.
* **Proposed Changes**: `protocol.md` and `coding-sheet.md`. Not an acceptance criterion of
  this study.

### Verification Plan

* **Lint**: `uv run ruff check src tests` clean.
* **Unit tests**: `uv run pytest` — the current 863 plus the new file; nothing requires a
  network or the full corpus.
* **Determinism gate**: two sample runs with one seed produce one file hash.
* **Pilot gate**: 20 items × 2 runs, four workers; seconds per item and disagreement
  reported; batch size fixed from the result and written into the protocol before the run.
* **Replay gate**: `eval perturb report` with every model key unset reproduces `table.txt`
  byte-for-byte from `responses.jsonl`.
* **Spot check**: five items hand-inspected — offsets point at the quoted text, the claim
  sentence is the one that cites, and the paraphrase shares no long run.
* **Acceptance**: 200 base items and a manifest that reproduces them; six arms with
  construction counts and intervals; the pre-registration dated before the first full run;
  the 30-item paraphrase check and the 60-paragraph OCR diagnostic counted in the report.

## Future Improvements

* **Voice arm done properly**: quote-anchored role labels, hand adjudication of 20 items, and
  a required `COURT_RESUMES_CUES` position check before a paragraph is called argument.
* **Overstatement arm (mode 8)**: needs a second, independent judge; the model cannot grade
  its own caution.
* **`support` on the holdout**: 313 human labels, with a second coder for drift.
* **The practitioner feature**: for a failed citation, retrieve and propose the paragraph
  that does support the proposition. Depends on this study's numbers.
* **Build script in the repository**: the M2 addendum's generator currently lives outside
  the tree; it moves to `scripts/` at the next regeneration.

<!-- Provenance: Indicates initial structural drafting via EGM. -->

*Drafted with EGM*
