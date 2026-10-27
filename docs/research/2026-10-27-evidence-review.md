# Ruchi — evidence review: what the code proves, what the literature says, where we are thin

*Prepared 27 October 2026. Feeds `/egm-brainstorm` for the next release.*

Purpose: before deciding what to build next, establish (a) what the repository actually
does and can prove, and (b) what the peer-reviewed and preprint literature on legal
citation checking established in 2024–2026. Every claim below cites either a file in this
repository or a published paper.

---

## 1. Codebase: what exists, and what it can prove

### 1.1 Size and shape

123 Python files under `src/` and `tests/`. Largest modules:

| module | lines | role |
|---|---|---|
| `cli.py` | 1640 | 20 commands (verify, find, contrary, draft, agent, eval, doctor, serve…) |
| `web/api.py` | 870 | FastAPI routes, jobs, annotated-brief export |
| `engine/contrary.py` | 822 | adversarial search against the user's proposition |
| `engine/citator.py` | 711 | subsequent treatment, bench-strength rule |
| `agent/tools.py` | 512 | eight `@tool` functions for the Strands agent |
| `engine/scope.py` | 300 | extent of support, quote verification |
| `engine/voice.py` | 338 | whose words a passage carries |

Test suite: **863 passed, 2 skipped** (~2 min). Corpus: 38,032 Supreme Court judgments,
1950–2025, 707,647 paragraphs, 79,508 citation aliases, 64,828 citation edges, 3.06 GiB in
one SQLite file.

### 1.2 The twelve failure modes from the PRD, and whether they are implemented and measured

| mode | implemented | measured on the eval set |
|---|---|---|
| 1 phantom | yes | 10 items, 100% recall |
| 2 mis-cite | yes | 10 items, 100% |
| 3 wrong court or bench | yes | 10 items, 100% |
| 4 pinpoint not there | yes | — |
| 5 wrong voice | yes | 10 items, 80% with a model |
| 6 dissent | yes | — |
| 7 obiter, not the holding | yes | — |
| 8 overstatement / dropped conditions | yes | — |
| 9 selective quotation | yes | **2 items** |
| 10 dead or wounded law | yes | 8 items, 100% |
| 11 distinguishable on facts | yes | — |
| 12 wrong pinpoint | yes | 10 items, 100% |

### 1.3 The measurement gap that matters most

The evaluation labels are not populated for the checks the project is proudest of.

`evals/gold.jsonl` (70 items) — null labels:

| label | null |
|---|---|
| `support` | **70 of 70** |
| `weight` | **70 of 70** |
| `applicability` | **70 of 70** |
| `voice` | 50 of 70 |
| `treatment` | 60 of 70 |

`evals/holdout.jsonl` (313 items) — `support` null in **274 of 313**, `weight` null in **313
of 313**, `applicability` null in **313 of 313**, `voice` null in 200, `treatment` null in
234.

Consequence: the engine reports a support grade, a weight grade and an applicability grade
on every citation, but the harness can only score existence, voice, treatment and pinpoint.
**"Extent of support" — the check that distinguishes this project from a citation lookup —
rests on 2 labelled items.**

### 1.4 Other facts worth carrying into the decision

- Abstention 66% on the Bedrock run: two of three verdicts end in "needs review".
- One false positive on 10 clean citations with a model configured (10%).
- The 313-item holdout is never used by default; `eval run` reads the 70-item gold set.
- The agent (8 tools) has **no evaluation at all**.
- Embeddings/dense retrieval are implemented and deliberately off: measured worse than
  BM25 on fragment recall (`evals/report-search-dense-bge.txt`).
- No Hindi or other Indian-language path; corpus is English only.
- 8 TODO/shortcut comments in the whole source tree — the code is not carrying hidden debt.

---

## 2. Literature, 2022–2026

### 2.1 The papers that define the problem we are solving

| paper | venue, year | finding that matters here |
|---|---|---|
| **Is this Citation on Point?** (arXiv 2608.12571) | 2026 | Proposition-level support verification by perturbing real citations. Models catch **93–100%** of wrong-case citations but only **37–61%** of wrong-pinpoint ones; GPT-5.4 with high reasoning still misses **40%** on court opinions, **18%** on briefs. Models accept a citation on **topical overlap** rather than page-level support. |
| **When Citations Mislead? A Claim-Level Benchmark (PARCEL)** (arXiv 2610.10971) | 2026 | 3,396 claims labelled Supported / Refuted / Not Found from real New York opinions. Best models reach 0.97 accuracy overall but **over-accept unsupported claims even with the full opinion in context**; missing support is harder to detect than contradiction. |
| **Who Checks the Citations? Benchmarking Legal Hallucination Detection** (arXiv 2606.21155) | 2026 | Over **1,000 real filings** containing fabricated citations, growing year over year. 1,300 brief excerpts with injected errors. Best agent (GPT-5) reaches **84.4% recall, 55.0% F1**, at **15.3 steps per excerpt**. Notes that subscription-only databases handicap everyone else. |
| **Hallucination-Free? Assessing the Reliability of Leading AI Legal Research Tools** — Magesh et al. | *Journal of Empirical Legal Studies*, 2024 | First preregistered evaluation of Lexis+ AI and Westlaw AI-Assisted Research: **17–33% hallucination** despite vendor "hallucination-free" claims. Proposes a hallucination typology. |
| **Large Legal Fictions** — Dahl, Magesh, Süzgün, Hangartner | *Journal of Legal Analysis*, 2024 | LLMs hallucinate on **58% (GPT-4) to 88% (Llama 2)** of verifiable questions about random federal cases, and do not reliably know when they are wrong. |

### 2.2 The papers that define how to build and evaluate it

| paper | venue, year | relevance |
|---|---|---|
| **Attributed Question Answering** — Bohnet et al. (arXiv 2212.08037) | 2022 | Formalises answer + attribution report, and an automatic attribution score. The shape our verdict board already takes. |
| **Atomic Fact Decomposition Helps Attributed QA** (arXiv 2410.16708) | 2024 | Splitting an answer into atomic facts before attributing each one. We decompose compound propositions (`decompose_claim`) but never measure it. |
| **IL-TUR: Benchmark for Indian Legal Text Understanding and Reasoning** (arXiv 2407.05399) | 2024 | Indian legal benchmark, English + Hindi + 9 regional languages, with a leaderboard. The reference point for "what Indian legal NLP should cover". |
| **ILDC for CJPE** (arXiv 2105.13562) | 2021 | 35k Indian Supreme Court cases — comparable in scale to our 38k corpus; established the Indian legal dataset tradition we sit in. |
| **Legal Research Bench** (arXiv 2610.00609) | 2026 | 413 expert-written US research questions. Best agent (Claude Opus 4.8) fully correct on **42.9%**; **more turns and higher cost do not predict accuracy**. |
| **Recognizing cited facts and principles in legal judgements** — Shulayeva, Siddharthan, Wyner | *AI & Law*, 2017 | Prior art for "what is this citation cited for" — facts versus principles. Directly adjacent to our support grading. |
| **Information extraction from case law and retrieval of prior cases** — Jackson et al. | *Artificial Intelligence*, 2003 | The original case for treating citation context, not citation existence, as the retrieval unit. |

### 2.3 What the literature implies for Ruchi

1. **Existence checking is a solved, commoditised problem.** Every benchmark shows
   wrong-case detection at 93–100%. Our mode 1/2/3 results sit exactly where the field is.
   It is not a differentiator.

2. **Page-level support is the open problem, and the field's best models fail it.**
   Wrong-pinpoint detection is 37–61%. Our mechanism is different in kind: we do not ask a
   model whether the page supports the claim, we ask the model to **produce a quote which we
   then string-match against the stored paragraph**. That is an attributable, auditable
   check the benchmarked systems do not have. If that mechanism is validated properly, it
   is a publishable claim, not just a capstone feature.

3. **The cheapest credible validation is a perturbation study, not more annotation.**
   "Is this Citation on Point?" swaps the cited case and then the pinpoint page in real
   citations. We can do exactly that on 200–500 real Indian citations from our own corpus,
   with no human labelling: take a real quote, then (a) point it at a different judgment,
   (b) point it at a different paragraph of the same judgment. Measure how often Ruchi
   catches each. The numbers are then directly comparable to a published paper.

4. **Coverage and precision must be reported together.** Our 66% abstention is honest but
   means two thirds of a brief gets no answer. Benchmarks report all-pass accuracy and F1,
   not only recall; we should report, per check: how often the check decided anything, and
   how often it was right when it did.

5. **Claim-level granularity is expected.** PARCEL grades one claim against one authority.
   Our unit is one citation with one proposition; a paragraph of a brief often carries two.
   We decompose some compound claims, but nothing measures whether that helps.

6. **Access is a policy argument in our favour.** "Who Checks the Citations?" explicitly
   names subscription-only case databases as a barrier. Ruchi runs on open data, locally,
   with no per-query fee. That is worth stating in the report, with that citation.

---

## 3. What lawyers actually want — and what we do not know

What the published evidence supports:

- Demand is real and growing: >1,000 filings with fabricated citations, year over year up.
- Trust in commercial tools is misplaced: 17–33% hallucination in the two market leaders.
- The failure practitioners miss is not the fake case, it is **the real case cited for
  something it does not say** (pinpoint/support). That is where a verdict board earns its
  place.
- Cost and access matter: tools priced per answer, or gated behind a subscription, exclude
  exactly the people most exposed (students, district-court advocates, pro se litigants).

What the published evidence cannot tell us, and only interviews can:

- Which of the twelve checks an Indian advocate wants to see first, and which are noise.
- Whether a grade A–F is the right output, or whether practitioners want a fix-it list
  ("here is the paragraph that does support your sentence").
- How much review-flagging is tolerable before the tool is abandoned.
- Whether the memo/draft output is used at all, or whether the verdict board alone is used.

**Status of our own user evidence: zero.** `docs/ROADMAP.md` WBS 7.2 ("three users and one
faculty member") is still marked in progress. No interview notes exist in the repository.
This is the single largest gap between what the project claims and what it can show, and it
cannot be closed by reading papers.

---

## 4. Where we are thin, ranked by what it costs us

| # | gap | evidence | how it hurts |
|---|---|---|---|
| 1 | No user study | WBS 7.2 open | M1 promised it; M2 asks for it; the product direction is still guesswork |
| 2 | `support`, `weight`, `applicability` unlabelled | gold 0/70, holdout 274/313 null | the differentiator is unmeasured; a panel can ask "how do you know it works" and there is no answer |
| 3 | Eval sets are small and synthetic | 70 gold, 313 holdout, one court, injected errors | weaker than any 2026 benchmark (1,300 excerpts, 3,396 claims, 413 questions) |
| 4 | No perturbation study | no such harness in `evaluation/` | the cheapest strong evidence, and the only way to compare against published numbers |
| 5 | Coverage not reported | abstention 66%, no coverage metric | honest but unusable without a second number; reads as "it declines most briefs" |
| 6 | Agent unmeasured | no eval under `agent/` | a T3 claim with no evidence behind it |
| 7 | English only | corpus is English | IL-TUR sets the expectation of Hindi and regional languages |
| 8 | No calibration between strict and recall modes | 10% false positives on clean citations | practitioners need to choose; we offer one operating point |

---

## 5. Three candidate scopes for the next release

**A. Evidence release (measurement only).**
Perturbation harness (wrong case / wrong paragraph) on 300 real citations; label support and
weight on the existing 313-item holdout; report coverage beside recall; run the planned
four interviews. No new product features. Makes every claim in the report defensible.

**B. Practitioner release (fix, not just find).**
Everything in A, plus: for a failed citation, retrieve and propose the paragraph or judgment
that *does* support the proposition, and write it into the annotated brief. Turns a grade
into an action. Needs A's measurement to know whether the suggestion is any good.

**C. Reach release (languages and coverage).**
Hindi judgment text and High Court judgments. Largest engineering effort, weakest evidence
base, and the one furthest from the capstone deadline.

The literature favours A before B: PARCEL and "Is this Citation on Point?" both show that
models over-accept unsupported claims, so a fix-it feature built without a measurement
harness would be graded on vibes. C is a different project in scope.

---

## 6. Sources

- Is this Citation on Point? arXiv:2608.12571 (2026)
- When Citations Mislead? PARCEL. arXiv:2610.10971 (2026)
- Who Checks the Citations? arXiv:2606.21155 (2026)
- Legal Research Bench. arXiv:2610.00609 (2026)
- Magesh, Surani, Dahl, Suzgun, Manning, Ho. Hallucination-Free? Assessing the Reliability
  of Leading AI Legal Research Tools. *Journal of Empirical Legal Studies* (2024).
  arXiv:2405.20362
- Dahl, Magesh, Suzgun, Ho. Large Legal Fictions: Profiling Legal Hallucinations in Large
  Language Models. *Journal of Legal Analysis* 6 (2024). arXiv:2401.01301
- Bohnet et al. Attributed Question Answering. arXiv:2212.08037 (2022)
- Atomic Fact Decomposition Helps Attributed Question Answering. arXiv:2410.16708 (2024)
- IL-TUR: Benchmark for Indian Legal Text Understanding and Reasoning. arXiv:2407.05399 (2024)
- ILDC for CJPE. arXiv:2105.13562 (2021)
- Shulayeva, Siddharthan, Wyner. Recognizing cited facts and principles in legal judgements.
  *Artificial Intelligence and Law* 25 (2017). doi:10.1007/s10506-017-9197-6
- Jackson, Al-Kofahi, Tyrrell, Vachher. Information extraction from case law and retrieval of
  prior cases. *Artificial Intelligence* 150 (2003). doi:10.1016/S0004-3702(03)00106-1
