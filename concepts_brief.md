# Ruchi — perturbation study and the evidence it must produce

* **Author:** Afjal Hussein (S24BCAU0171)
* **Date:** 2026-10-27
* **Status:** concepts brief, after six-lens Goldfish review

## Overview

Ruchi checks whether the citations in an Indian legal brief are real, say what the brief
claims, are in the voice the brief attributes to them, and are still good law. It runs on a
local corpus of 38,032 Supreme Court judgments.

The next release adds no new user-facing feature. It adds the evidence the project does not
have: a **perturbation study** over real citations taken from the corpus, in which each
citation is broken in one known way and the engine is measured on whether it notices.

The unit is a citation occurrence, not a document: a sentence from a later judgment that
quotes a paragraph of an earlier judgment, together with the citation it used. Because the
sentence really does quote that paragraph, the clean version is a correct citation by
construction. Every corrupted version has one deliberate defect. That removes the need for
human annotation of support, which is what blocked measurement until now.

This is a design-phase brief. No implementation starts until the spec in
`docs/designs/perturbation-study.md` is approved.

## Analysis

### What the review changed

Six independent reviewers read the first version of this concept. Their objections
converged on five points, and the design changed accordingly.

**1. The control was not a control.** A citation that exists is not a citation whose claim
is supported, so 300 "clean" citations could have been contaminated, and a correct flag
would have been scored as a false alarm. *Resolved:* the clean arm is built only from items
where the later judgment quotes at least eight consecutive words of the cited paragraph,
verified by string match at sampling time. Clean arms are scored **only on pointer findings**
(mode 2 mis-cite, mode 4 pinpoint missing, mode 12 wrong pinpoint). They may legitimately
carry a voice finding — a court quoting counsel — and that must not count as an alarm.

**2. Abstention makes every catch rate meaningless on its own.** Two of three verdicts
currently end in "needs review". Counting an abstention as a catch inflates the number;
counting it as a miss deflates it. *Resolved:* four outcomes per item — clean pass, correct
flag, wrong flag, abstention — and three numbers per arm: decided-only catch (primary),
all-in catch, abstention. One operating point is pre-registered before the first run.

**3. The arms were not measuring one thing.** Swapping a judgment, swapping a paragraph and
rewriting a claim exercise four different subsystems. A pooled "catch rate" would describe
none of them. *Resolved:* arms are grouped into two families and never pooled. Pointer
family (wrong judgment, wrong paragraph, adjacent paragraph) reports the mode that fired.
Claim family (counsel's words attributed to the court) reports voice only.

**4. Two of the six arms could not be scored honestly.** The overstatement arm depends on
the model answering "partial" — if it answers "full", no finding is produced, so the arm
would measure model caution rather than the verifier. And the counsel arm previously drew
its sentences from `attribute_voice`, the very detector under test. *Resolved:*
overstatement is cut from this study and named as future work; the voice arm now draws its
ground truth from `paragraph.role = argument_*`, a label independent of the detector
(5,943 counsel paragraphs available).

**5. The comparison to published numbers was overstated.** The 37–61% figure in
*Is this Citation on Point?* (arXiv:2608.12571) comes from models reading a supplied page in
US documents. Ruchi localises the paragraph inside a judgment and verifies a quote by string
match. *Resolved:* the report compares mechanism to mechanism — "same perturbation family" —
and states the protocol differences. It does not claim a head-to-head win.

### The defect the reviews found in the code

`ingest/store.py` hard-codes `ocr_derived=False` for every text version, while a large part
of the older corpus is plainly OCR output ("prcx:eed1ngs", "parciigraph"). `find_quote`
refuses fuzzy matching when text is not marked OCR-derived. If the flag is wrong, quotes
from older judgments fail verification, and every rate in the study is distorted along
exactly the decade axis the report intends to publish. This must be spot-checked and, if
confirmed, fixed before sampling. It is the one change to product code this phase allows,
because without it the measurement is not trustworthy.

### What the study is not

The sample comes from citations that courts made to each other. Practitioner briefs
paraphrase more than courts quote. Every rate in this study is therefore an **upper bound**
on performance against a real brief, and the report says so in the same sentence as the
number rather than in a limitations section at the end.

## Goals vs. Non-Goals

**In scope**

1. A frozen sample of 200 base citations, each with a manifest: corpus hash, repository
   commit, model id, region, prompt versions, sampling seed, candidate `top_k`.
2. Five arms, 200 items each, within-subject: clean pointer, wrong judgment, wrong
   paragraph, adjacent paragraph, counsel-attributed-to-court.
3. One command — `orderorder eval perturb` — that reproduces the table from cache without
   new model calls.
4. Per-arm catch, abstention and false alarms with Wilson intervals; decade and bench size
   reported descriptively, with a minimum cell size of 10 or not at all.
5. A four-question interview kit, transcripts, and a coding sheet for three users and one
   faculty member — run in the first week, described as formative, not as validation.
6. One small visible product delta drawn from the results: a strict / recall operating point
   that sets the confidence threshold and review policy from the command line.

**Out of scope**

1. Any new check, any new failure mode, any new user interface.
2. The overstatement arm and the applicability check — both need a model judgement that
   cannot currently be scored without circularity.
3. Hand-labelling `support` across the 313-item holdout. Worth doing, too slow for 09 Nov.
4. Hindi text, High Court judgments, or a wider corpus.
5. "Here is the authority that does support you" — the practitioner feature that follows
   this study, not part of it.
6. Any change to the default verdict behaviour except the new opt-in operating point.

## Key Decisions & Staging for Next Steps

| # | decision | reason |
|---|---|---|
| 1 | Unit is a citation occurrence with a verbatim quote | gives clean ground truth without annotation |
| 2 | Five arms, not six | overstatement cannot be scored without circularity |
| 3 | Clean arm scored on pointer modes only | a voice finding on a clean citation is not an alarm |
| 4 | Primary metric is decided-only catch, with abstention beside it | 66% abstention would otherwise dominate every number |
| 5 | Arms are never pooled; pointer and claim families reported apart | four subsystems, four different meanings |
| 6 | Voice ground truth from `paragraph.role` | the detector must not grade its own homework |
| 7 | Fix the OCR flag before sampling | otherwise the decade comparison is an artefact |
| 8 | Comparison framed as family, not superiority | different jurisdiction and different task |
| 9 | Interviews in week one | they can change what the numbers mean; after 02 Nov they can only decorate |
| 10 | Freeze scope 02 Nov, submission 09 Nov | the report and demo need the numbers before the deadline, not on it |

**Acceptance criteria**

- 200 frozen items with a manifest that reproduces the sample byte-for-byte.
- Five-arm table with intervals, regenerable from cache with no network.
- Pre-registration file dated before the first run.
- Four interview transcripts and a coding sheet.
- The report's accuracy section quotes the table and the "upper bound" sentence.

**Open risks**

| risk | consequence | mitigation |
|---|---|---|
| OCR flag finding is wrong | the study measures OCR noise, not verification | spot-check 20 items from three decades before sampling |
| The clean arm is not clean | false-alarm rate is meaningless | admit only items with an 8-word verbatim quote; report yield |
| Provider failover answers one item with two models | unreproducible table | pin one model, disable fallbacks for the run, log model per item |
| Adjacent paragraphs often do support the claim | the arm's ground truth is contested | adjudicate 30 adjacent items by hand, report agreement, drop repeats |
| Compute or schedule slips | half a table at the viva | cut to 120 items per arm; the protocol does not change |
