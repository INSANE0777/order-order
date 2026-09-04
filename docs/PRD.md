# OrderOrder — Product Requirements Document

| | |
|---|---|
| **Product name** | OrderOrder (trademark and domain clearance outstanding, see §15.5) |
| **Version** | 0.1, draft for co-founder review |
| **Date** | 4 September 2026 |
| **Owners** | Developer (product, engineering, infrastructure); law-student co-founder (domain rules, evaluation data, users) |
| **Status** | Hackathon MVP scope agreed; startup phases sketched |
| **Companion documents** | [ARCHITECTURE.md](ARCHITECTURE.md) · [TECH_STACK.md](TECH_STACK.md) · [ROADMAP.md](ROADMAP.md) |

---

## 1. Summary

OrderOrder is a self-hosted citation-integrity engine for Indian case law. It reads a brief, moot-court memorial, written submission or research paper, finds every case-law citation, and answers three questions **separately** for each one:

1. **Does the case exist?** (and is the citation string correct)
2. **Which paragraph is being relied on?** (pinpointed inside a judgment that may run to 300 pages)
3. **Does that paragraph support the proposition to the extent claimed?** (or has the author stretched two lines of a fact-bound observation into a general rule)

It then writes what opposing counsel would say about each citation, and suggests how to fix it.

The same engine sits behind a drafting assistant: give it the case file and the facts, and it produces a written submission in which every proposition is bound to a real judgment and a real paragraph, and nothing enters the draft that the verifier could not confirm.

Two surfaces, one engine:

| Surface | Input | Output |
|---|---|---|
| **A. Citation Stress-Test** | A brief, memorial, submission or paper (PDF, DOCX or pasted text); optionally the facts of the matter | A verdict for every citation, an annotated copy of the brief, an opposing-counsel memo, and a verification report |
| **B. Verified Drafting** | Case documents (pleadings, contracts, notices, orders, scanned annexures, images) plus a narrative of facts | Case digest, framed issues, ranked authorities, a draft written submission with table of authorities, and a verification appendix |

The MVP targets moot-court students and junior litigators. The corpus is Supreme Court of India judgments from open, licence-clean sources. In production everything runs on hardware the team controls and no client document leaves the box unless the user explicitly turns on a cloud model; the hackathon build costs nothing, running on free API tiers with demo data only (§8).

---

## 2. The problem

### 2.1 Where case law enters the day

For a law student the two things that matter most are **moot courts** (a full courtroom simulation) and **written work** (research papers, blogs, articles). After that come **internships** in law firms, companies and courts. For a practising lawyer, whether in court or in a company reviewing a contract dispute, the rule is the same: **an argument is not acceptable until it is backed by case law.**

Case law usually means Supreme Court judgments, because under Article 141 of the Constitution the law declared by the Supreme Court binds every court in India. High Court judgments are different: a Punjab and Haryana High Court decision binds courts in that state but has only persuasive value before the Jammu and Kashmir and Ladakh High Court. Bench strength matters too: a two-judge bench of the Supreme Court cannot override a five-judge bench.

Whatever the forum, **everything first goes in as a written submission**. Oral argument in court, oral rounds in a moot, a research paper: all of them rest on a written document in which every proposition carries a citation and an analysis of why the cited case applies. The standard shape is:

> Company A sues Company B for fraud in a contract. The submission explains the facts, then says: in *X v. Y* the Supreme Court laid down four parameters for what constitutes fraud; the facts here satisfy all four; therefore fraud is made out.

Every link in that chain has to be established, and the other side will test every link.

### 2.2 Three levels of citation failure

| Level | Failure | How hard to catch today |
|---|---|---|
| 1 | **The case does not exist.** Generative AI fabricates plausible-looking citations; tired juniors mistype volume and page numbers. | Easy. Search SCC Online, Manupatra, Indian Kanoon or the Supreme Court's SCR portal. Minutes. |
| 2 | **The case exists but where does it say that?** A judgment can be 10, 50 or 300 pages. Which paragraph, which line? Has it since been overruled? | Tedious. Nobody reads 300 pages per citation. Asking an AI to find it produces confident answers that are often wrong. |
| 3 | **The case says something, but not that.** The judgment made a two-line observation in a specific factual setting. The brief cites it for a broad rule. Or the judgment said one thing and the brief claims five, four of them the author's own "masala". Or all five things were said, but the facts of the present matter are different and the judgment does not apply. | Very hard. Verifying it means reading the whole judgment with the brief's sentence in mind, for every citation, on both sides. |

Level 3 is the real product. It is where arguments are won and lost, where opposing counsel earns their fee, and where no existing tool helps.

### 2.3 Why current AI makes it worse

General-purpose assistants will readily say "yes, this judgment holds that" without having read it, and will invent paragraph numbers. Even research tools with retrieval behind them are measured to hallucinate: Stanford RegLab found Lexis+ AI hallucinated on roughly 17% of queries and Westlaw's AI-assisted research on roughly 33% ([source](https://reglab.stanford.edu/publications/hallucination-free-assessing-the-reliability-of-leading-ai-legal-research-tools/)). In the CLERC benchmark GPT-4o reached 89.9% citation recall but only 52.8% citation precision: it cites plausibly and wrongly ([source](https://arxiv.org/pdf/2406.17186)). The Princeton "Who Checks the Citations?" benchmark (August 2026) found that *content misrepresentation*, a real case cited for something it does not support, was the hardest hallucination type for every model tested ([source](https://arxiv.org/html/2606.21155)).

The co-founder's framing of the loophole is exact: the tool must say, for every claim in a brief, whether the judgment supports it **to the same limited extent** the author claims, whether the author has oversold it, and whether the facts even match.

### 2.4 Evidence that this is now urgent

| When | Forum | What happened | Source |
|---|---|---|---|
| Jun 2023 | S.D.N.Y., USA | *Mata v. Avianca*: six fabricated cases in a brief; $5,000 sanction on the lawyers | [Wikipedia](https://en.wikipedia.org/wiki/Mata_v._Avianca,_Inc.) |
| Aug 2023 | Delhi High Court | *Christian Louboutin v. Shutiq*: court warned against ChatGPT's "fictional case laws" | [LiveLaw](https://www.livelaw.in/articles/phantom-precedents-ai-generated-case-law-indian-courts-526665) |
| Dec 2024 | ITAT Bengaluru | *Buckeye Trust v. PCIT*: three fake Supreme Court judgments and one fake Madras HC ruling in a ~₹669 crore matter; order recalled | [iPleaders](https://blog.ipleaders.in/ai-hallucinated-case-law-fake-citations-india/) |
| Aug 2025 | Andhra Pradesh | A junior civil judge's order cited four non-existent Supreme Court judgments; the High Court recognised them as AI-generated; the Supreme Court took suo motu cognizance in Feb 2026 | [Verdictum](https://www.verdictum.in/court-updates/high-courts/andhra-pradesh-high-court/gummadi-usha-rani-v-sure-mallikarjuna-rao-civil-revision-petition-no-2487-of-2025-artificial-intelligence-trial-court-fake-citation-1605575) |
| Sep 2025 | Delhi High Court | A petition quoted "paragraphs 73 and 74" of *Raj Narain v. Indira Nehru Gandhi*, (1972) 3 SCC 850, a judgment with **27 paragraphs**; petition withdrawn | [LiveLaw](https://www.livelaw.in/articles/phantom-precedents-ai-generated-case-law-indian-courts-526665) |
| Oct 2025 | Bombay High Court | A ₹27.91 crore faceless tax assessment quashed because it rested on three non-existent precedents | [LiveLaw](https://www.livelaw.in/articles/phantom-precedents-ai-generated-case-law-indian-courts-526665) |
| Jan 2026 | Bombay High Court | ₹50,000 costs for fake case law in written submissions that still carried raw AI formatting | [LiveLaw](https://www.livelaw.in/articles/phantom-precedents-ai-generated-case-law-indian-courts-526665) |
| **Jul 2026** | **Supreme Court of India** | ***Pooja Ramesh Singh v. Jammu and Kashmir Bank Ltd*, 2026 SCC OnLine SC 1258** (Narasimha and Aradhe JJ): NCLT and NCLAT orders set aside for relying on non-existent AI-generated judgments. Citing such judgments without verification is "misconduct on the part of an advocate"; a decision resting on hallucinated material "is no decision in the eyes of the law"; the Bar Council of India was directed to frame guiding principles with disciplinary consequences. | [LiveLaw](https://www.livelaw.in/supreme-court/citing-ai-generated-fake-precedents-is-advocate-misconduct-judgments-based-on-them-are-void-supreme-court-539634) · [SCC blog](https://www.scconline.com/blog/post/2026/07/03/supreme-court-on-ai-hallucinated-judgments-and-fake-citations/) |

The Delhi High Court incident is the level-2 failure in its purest form: a pinpoint to paragraphs that do not exist. The Supreme Court judgment turns citation verification from a nicety into a professional obligation with disciplinary teeth.

> Note on our own citation: the research for this document also surfaced a neutral citation "2026 INSC 668" for the Supreme Court judgment above. Neither primary source confirms it, so the SCC OnLine citation is used and the neutral citation is marked as unconfirmed. This is exactly the discipline the product enforces.

---

## 3. Why now

- **Regulators have named the use case.** The Supreme Court's draft *Regulations for Use of Artificial Intelligence (AI) in Courts, 2026* (published 3 June 2026 under the Court's AI Committee, applying to the Supreme Court, High Courts, tribunals and statutory adjudicators) expressly list **citation verification** among permitted assistive uses, while prohibiting AI adjudication and making "the model hallucinated" no defence ([LiveLaw](https://www.livelaw.in/top-stories/supreme-court-publishes-draft-regulations-on-ai-use-in-judiciary-invites-feedback-536746) · [The Leaflet](https://theleaflet.in/law-and-technology/explained-the-supreme-court-of-indias-draft-regulations-for-use-of-artificial-intelligence-in-courts-2026)). Kerala High Court's July 2025 policy was India's first binding judicial AI policy ([PDF](https://images.assettype.com/theleaflet/2025-07-22/mt4bw6n7/Kerala_HC_AI_Guidelines.pdf)). The Bar Council of India constituted a digital-ethics sub-committee in June 2026 covering fabricated citations ([SCC blog](https://www.scconline.com/blog/post/2026/07/18/bci-social-media-digital-ethics-guidelines/)).
- **A licence-clean corpus exists.** AWS Open Data hosts the Indian Supreme Court judgments 1950-2025 and the judgments of all 25 High Courts under CC-BY-4.0 (§11). Two years ago building a legal knowledge base in India meant scraping.
- **Open-weight models are good enough, run locally, and are served free.** 2026-generation 27-31B models with 256K context, Apache-2.0 licences and schema-constrained JSON output run on one 24 GB GPU, so self-hosting is a feature, not a compromise; and the same open models are served on free API tiers by several providers, which is what makes a ₹0 hackathon build possible (see [TECH_STACK.md](TECH_STACK.md)).
- **Incumbents are racing to "AI-enabled search", not verification.** SCC Online launched AI Pro (Feb 2026) and partnered with Harvey (Jan 2026); Manupatra sells AI search with overruled-flags. None checks the extent of support (§13).

---

## 4. Users

| Persona | Situation | Job to be done | Willingness to pay | Reach |
|---|---|---|---|---|
| **The Mooter** (law student, years 2-5) | Drafting a memorial for a national moot; the opposing team will attack every authority | "Tell me which of my citations will not survive the bench, before the other side does." | Low individually; institutions and moot societies pay | Co-founder's college and the moot circuit |
| **The Researcher** (student or academic) | Writing a paper, blog or article that quotes holdings | "Give me the exact paragraph and confirm I am not overstating it." | Low; free tier | Law-school writing centres |
| **The Intern** (law-firm or chambers intern) | Asked to "verify the citations in this draft" or "find authorities for X" overnight | "Check 40 citations by morning and show my senior the paragraphs." | Firm pays | Firm partnerships |
| **The Litigator** (junior to mid-level advocate) | Filing written submissions; receiving the other side's | "Stress-test my brief; break theirs." | Medium, subscription in INR | Bar associations, chambers |
| **The In-house Counsel** | Contract dispute, legal notice, arbitration | "Draft a defensible position with authorities I can trust." | Medium to high, seats | Direct sales |

Secondary, later: judges' law clerks and tribunal registries, for whom the draft regulations explicitly permit citation verification.

**Wedge.** Moot-court students first. They have the fastest feedback loop, the co-founder has distribution inside a law school, memorials are a ready-made adversarial test corpus, and every mooter becomes a junior associate within two years. India has roughly 2 million registered advocates ([Ministry of Law and Justice](https://legalaffairs.gov.in/sites/default/files/AU2827.pdf)); no unprovenanced market-size figures are used in this document.

---

## 5. Product principles (hard requirements)

These are not aspirations; each is testable and each maps to a mechanism in [ARCHITECTURE.md](ARCHITECTURE.md) §1.

1. **Quote-or-nothing.** A claim is marked "supported" only if the system holds a verbatim quote from the judgment that it has string-matched against the stored text. No quote, no support.
2. **Closed world.** The language model never recalls a case from memory. It only reads text that the retrieval layer pulled from the verified corpus. Citations it "remembers" are treated as unresolved until the resolver finds them.
3. **Three verdicts, never one.** Existence, location and extent-of-support are reported separately. "The case exists" is never allowed to imply "the case says this".
4. **Adversarial by default.** The output is written in the voice of opposing counsel. The product's job is to break the citation, not to reassure the author.
5. **The lawyer decides.** OrderOrder produces memos, pinpoints and drafts. It files nothing, sends nothing, and states on every output that it is a research aid, not legal advice. This matches the human-verification requirement in the draft regulations.
6. **Every verdict is auditable.** Canonical paragraph ID, reporter, text version, quote, character offsets and source URL travel with every verdict, so a reader can check the check.
7. **Temperature is not a safety mechanism.** Low sampling temperature is a minor knob. Grounding, retrieval quality and string verification are what stop hallucination.
8. **Abstain rather than guess.** Every stage may return "needs human review" with a reason. An honest "could not verify" is a valid, first-class outcome.

---

## 6. The twelve ways a citation lies

Each failure mode has a detector in the engine and a label in the evaluation gold set. The numbers are used throughout the companion documents.

| # | Failure mode | Example | Detector |
|---|---|---|---|
| 1 | **Phantom** | The case does not exist in any reporter or court record | Resolver |
| 2 | **Mis-cite** | Right case, wrong volume/year/page; or a real name attached to a different case's citation | Resolver |
| 3 | **Wrong court or bench** | A High Court decision passed off as Supreme Court; a 2-judge bench cited against a settled 5-judge bench | Metadata and hierarchy check |
| 4 | **Not there** | The case exists but says nothing of the sort | Locator |
| 5 | **Wrong voice** | The passage is the court summarising counsel's argument, quoting the High Court below, quoting another judgment, or an editorial headnote | Voice attribution |
| 6 | **Minority opinion** | The passage is from a dissent | Opinion attribution |
| 7 | **Obiter as ratio** | A passing observation cited as the holding | Weight classifier |
| 8 | **Overstatement** | The court held X where conditions A and B were present; the brief claims X generally. "May" becomes "must"; a Section 17 point becomes "all commercial contracts" | Scope comparator |
| 9 | **Selective quotation** | The qualifier, proviso or "in the facts of this case" is cut off | Scope comparator |
| 10 | **Dead or wounded law** | Overruled, reversed on appeal, referred to a larger bench, superseded by amendment, doubted | Citator |
| 11 | **Distinguishable** | Everything above is fine but the facts of the present matter are materially different | Fact comparator |
| 12 | **Wrong pinpoint** | Right case, right proposition, wrong paragraph; or the paragraph number is from a different reporter's numbering | Locator with cross-reporter map |

The Princeton benchmark's five hallucination types (non-existent citation, name/reporter mismatch, incorrect pincite, verbatim misquote, content misrepresentation) map onto items 1, 2, 12, 9 and 8 respectively; the taxonomy here is a superset.

---

## 7. Functional requirements

Priority: **P0** = hackathon MVP; **P1** = phase 1 (first three months after); **P2** = later.

### 7.1 Surface A: Citation Stress-Test

**User story.** As a mooter, I upload my memorial and within ten minutes I see every citation graded, the exact paragraph each one rests on, and what the other side will say about it.

| ID | Requirement | Priority | Acceptance criteria |
|---|---|---|---|
| A1 | Accept a brief as PDF, DOCX or pasted text; extract body text preserving footnotes | P0 | 95% of citations in the demo memorial are detected |
| A2 | Detect every case-law citation and the proposition it is attached to (the sentence or clause it supports) | P0 | Citation spans and proposition spans shown in the annotated brief |
| A3 | Resolve each citation to a canonical judgment; handle parallel citations (SCC, AIR, SCR, SCALE, JT, INSC, HC neutral citations, Indian Kanoon IDs) and fuzzy party names | P0 | Phantom and mis-cite detection recall ≥ 99% on the gold set |
| A4 | Report the existence verdict with the resolution evidence (matched citation, court, date, bench, source URL) | P0 | Every resolved citation shows its source |
| A5 | Locate the supporting paragraph(s) inside the judgment; return canonical paragraph IDs, verbatim quotes, character offsets and the text version used | P0 | Pinpoint hit@3 ≥ 85% on the gold set; quote-grounding rate 100% |
| A6 | Verify a user-supplied pinpoint ("para 23") against the located paragraph and flag cross-reporter numbering mismatches | P0 | Detects the "para 73 of a 27-paragraph judgment" case |
| A7 | Classify support level: full, partial, none, contradicted; with a plain-language gap description and the dropped qualifiers | P0 | Support-level macro-F1 ≥ 0.70 |
| A8 | Attribute voice: court's own reasoning vs counsel's argument vs lower court vs quoted precedent vs headnote | P0 | Detects the planted counsel-argument case |
| A9 | Attribute opinion: majority, concurring, dissenting; report bench strength | P0 | Detects the planted dissent case |
| A10 | Classify weight: ratio vs obiter, with the reasoning | P1 (simple version P0) | Agreement with annotators ≥ 75% |
| A11 | Report subsequent treatment: overruled, reversed, referred to larger bench, distinguished, doubted, followed; with the treating judgment and paragraph | P0 (from Indian Kanoon cited-by), P1 (own citator graph) | Detects the planted overruled case |
| A12 | Compare the facts of the user's matter (if supplied) with the facts of the cited case; list material similarities and differences | P1 (simple version P0) | Produces a distinguishing argument for the planted mismatch |
| A13 | Write an opposing-counsel memo per citation: strength grade, attack vectors, and fix suggestions (narrow the proposition, cite the pinpoint, add a stronger authority, acknowledge the distinguishing fact) | P0 | Reviewed by the co-founder as "what a competent opponent would say" |
| A14 | Produce a verdict board (all citations at a glance), an annotated brief (inline flags), and a downloadable verification report (PDF) | P0 | Demo walkthrough |
| A15 | Check a batch of briefs (e.g. all memorials in a moot) and export a CSV summary | P2 | — |
| A16 | Stress-test the *other side's* brief in the same flow | P0 | Same pipeline, no extra work |

### 7.2 Surface B: Verified Drafting

**User story.** As a junior litigator, I upload the pleadings, the contract and the notices, describe the facts, and get a written submission in which every proposition is tied to a verified paragraph, plus a list of the authorities the other side will use against me.

| ID | Requirement | Priority | Acceptance criteria |
|---|---|---|---|
| B1 | Accept a matter's documents: PDFs (born-digital and scanned), images (photographed pages), DOCX; English and Hindi text | P0 | OCR of scanned English pages ≥ 95% character accuracy on the demo set |
| B2 | Build a case digest: parties, relationship, timeline of events, documents, statutory provisions involved, reliefs sought; user edits and confirms | P0 | Digest reviewed and accepted by the user before drafting |
| B3 | Propose legal issues from the digest; user edits, reorders and confirms | P0 | — |
| B4 | For each issue, retrieve candidate authorities from the local knowledge base, then from official online sources if coverage is thin; rank by court, bench strength, recency, treatment status and relevance | P0 | Top-10 candidates include the gold authority for the demo matter |
| B5 | Generate propositions per issue, each bound to a specific judgment and paragraph, and pass every proposition through the Surface A engine before it enters the draft | P0 | Zero unverified propositions in the exported draft |
| B6 | Verification gate policy: by default only "supported, court's own voice, majority, good law" passes; partial support is included only with a visible warning; user can override with an acknowledgement | P0 | Gate decisions visible per proposition |
| B7 | Assemble the draft in Indian written-submission format: synopsis, list of dates, issues, arguments, prayer, table of authorities in SCC / neutral-citation style | P0 | Template approved by the co-founder |
| B8 | Self-attack: run the stress-test on the generated draft and surface counter-authorities the opponent could cite | P0 (stress-test), P1 (counter-authorities) | Self-attack panel populated |
| B9 | Export DOCX and PDF with a verification appendix (every citation, paragraph, quote, treatment) | P0 | Opens cleanly in Word |
| B10 | Moot-court mode: bench memorandum and likely questions from the bench | P2 | — |
| B11 | Verify statutory-provision quotations against bare-act text | P2 | — |

### 7.3 Shared platform requirements

| ID | Requirement | Priority |
|---|---|---|
| S1 | Local knowledge base of Supreme Court judgments built from AWS Open Data with paragraph-level structure, canonical paragraph IDs, per-reporter numbering map and a once-per-judgment digest cache | P0 (subset), P1 (full SC corpus) |
| S2 | On-demand fetch from official/open online sources (Indian Kanoon API with attribution, SCR portal, eCourts judgment portal, Supreme Court website) with write-back into the knowledge base | P0 (Indian Kanoon), P1 (others) |
| S3 | Judgment viewer with paragraph highlights, opinion boundaries, role labels, reporter and text-version badges | P0 |
| S4 | Matter workspace grouping uploads, briefs, drafts and reports; per-matter isolation | P0 (single user), P1 (teams) |
| S5 | Accounts, roles (owner, member, reviewer), audit log | P0 (basic), P1 |
| S6 | Admin console: job queue, corpus coverage, model settings, source quotas, cloud toggle | P1 |
| S7 | High Court corpus by court; tribunals later | P1 (2-3 HCs), P2 |
| S8 | Bring-your-own-login connectors for Manupatra / SCC Online using the user's own session for lookups; no bulk retrieval | P2 |
| S9 | Word add-in and browser extension | P2 |

### 7.4 Explicit non-goals for the MVP

- Giving legal advice or predicting outcomes.
- Verifying statutes, foreign judgments (UK/US cases that Indian courts cite), or commentaries; the resolver recognises them and marks them "not verified in this version".
- Regional-language judgments; English judgments only, Hindi OCR for uploaded case files only.
- Multi-stage matter disambiguation beyond date and bench (interim orders, review, curative).
- Real-time collaboration, billing, marketplaces.

---

## 8. Non-functional requirements

| Area | Requirement |
|---|---|
| **Accuracy** | Targets in §12; quote-grounding rate is 100% by construction (a verdict cannot say "supported" without a string-matched quote) |
| **Latency** | A 30-citation brief verified in under 10 minutes on the production GPU box; under 60 seconds for a single citation whose judgment is already digested |
| **Self-hosting** | The production requirement: every component can run on hardware the team controls, from a laptop (reduced models) to a rented India-resident GPU server, with no mandatory external API. The hackathon build instead runs the language model on free cloud API tiers with fallbacks and uses free GPU notebooks for batch work, on non-privileged demo data only; the provider is a configuration value, so the switch to self-hosted models is not a code change |
| **Confidentiality** | Per-matter isolation, encryption at rest, TLS in transit, audit log of every access and export, delete-on-request, no training on user data, upload malware scanning |
| **Auditability** | Every verdict stores its evidence (paragraph IDs, quotes, offsets, text version, source URL, model and prompt version) |
| **Determinism** | Same brief, same corpus, same model version gives the same verdicts; all LLM calls use schema-constrained output and are logged |
| **Availability** | Hackathon: best effort. Phase 1: 99% monthly for the web app; batch jobs resumable |
| **Cost** | The hackathon build costs ₹0 (free tiers and local CPU; bill of materials in [TECH_STACK.md](TECH_STACK.md) §12). In production the per-judgment digest is computed once and cached, and per-citation verification stays under ₹5 of GPU time |
| **Licensing** | Only permissive-licence components in the product path (MIT, Apache-2.0, BSD, CC-BY); AGPL, non-commercial and revenue-capped licences are excluded (list in [TECH_STACK.md](TECH_STACK.md)) |
| **Attribution** | "Powered by IKanoon" attribution wherever Indian Kanoon data is shown or used for retrieval context; AWS Open Data datasets cited per their CC-BY terms |

---

## 9. User experience

### 9.1 Stress-test flow

1. **Upload** a brief (PDF/DOCX/paste). Optionally paste the facts of the matter or link a matter workspace.
2. **Verdict board** fills in live as jobs complete: one row per citation with grade (A-F), existence, pinpoint, support, voice, weight, treatment, applicability. Sort by weakest first.
3. **Annotated brief**: the original text with inline flags at each citation; click a flag to open the verdict.
4. **Judgment viewer**: the cited judgment with the located paragraph highlighted, opinion boundary and role label shown, a badge for reporter and text version, and the user's claimed pinpoint compared with the located one.
5. **Opposing-counsel memo**: per citation, the attack in prose, then fixes.
6. **Export**: verification report (PDF), annotated brief (DOCX with comments), CSV of verdicts.

### 9.2 Drafting flow

1. **Matter workspace**: upload documents; OCR and parsing progress shown per file; low-confidence pages flagged for the user to eyeball.
2. **Case digest review**: parties, timeline, documents, provisions, reliefs; edit and confirm.
3. **Issues**: proposed list; edit, reorder, confirm.
4. **Authorities**: per issue, ranked candidates with digest cards (holding, conditions, bench, treatment); pick or let the engine choose.
5. **Draft**: the written submission with a verification badge on every proposition; hover to see quote and paragraph; gate warnings visible.
6. **Self-attack panel**: what the other side will say; counter-authorities.
7. **Export**: DOCX/PDF with table of authorities and verification appendix.

### 9.3 Design notes

- Every screen shows the disclaimer line and the model version used.
- "Needs human review" is a visible state with a reason, never hidden behind a low score.
- Attribution for Indian Kanoon appears wherever its data is shown.

---

## 10. Outputs

| Output | Contents |
|---|---|
| **Verdict board** | One row per citation; grade; the eight verdict dimensions; links |
| **Annotated brief** | Original text with inline flags; DOCX export with comments |
| **Opposing-counsel memo** | Per citation: what is wrong, why it matters, how the opponent will phrase it, how to fix it |
| **Verification report (PDF)** | Cover summary, table of authorities with status column, per-citation evidence pages (paragraph text, quote, offsets, source), methodology and model-version note |
| **Draft written submission (DOCX/PDF)** | Indian format; table of authorities; verification appendix |
| **Machine-readable** | JSON verdicts (schema in [ARCHITECTURE.md](ARCHITECTURE.md) §8), CSV summary |

---

## 11. Data sources and legal basis

| Source | What | Access | Licence / terms | Role in OrderOrder |
|---|---|---|---|---|
| **AWS Open Data: Indian Supreme Court Judgments** | 1950-2025, JSON and parquet metadata, zipped judgment text in English and regional languages; bi-monthly refresh; maintained by Dattam Labs | S3 bucket `indian-supreme-court-judgments` (ap-south-1), no account needed | CC-BY-4.0 ([registry](https://registry.opendata.aws/indian-supreme-court-judgments/)) | **Primary knowledge-base corpus** |
| **AWS Open Data: Indian High Court Judgments** | 25 High Courts; PDFs, JSON and parquet; quarterly refresh; the maintainer's repository reports ~17.8M judgments, ~1.25 TiB | S3 bucket `indian-high-court-judgments` | CC-BY-4.0 ([registry](https://registry.opendata.aws/indian-high-court-judgments/) · [repo](https://github.com/vanga/indian-high-court-judgments)) | Phase 1-3 corpus, court by court |
| **Supreme Court SCR portal** (`scr.sci.gov.in`) | Official Supreme Court Reports since 1950 (~36k cases), neutral-citation search, PDFs; eSCR and digiSCR merged into it | Web, free, no API | Public judicial record | **Authoritative text anchor** for pinpoints |
| **Supreme Court judgment PDFs** (`api.sci.gov.in`) | Official PDFs carrying the `YYYY INSC N` neutral citation on page one | Predictable URLs | Public judicial record | Text-version anchor; neutral-citation key |
| **Indian Kanoon API** | Search, document, document metadata, in-document fragment search, cited-by and cites lists (up to 50 each) | Token or HMAC auth; prepaid: search ₹0.50, document ₹0.20, fragment ₹0.05, metadata ₹0.02 per call; ₹500 signup credit; ₹10,000/month free for verified non-commercial use | Mandatory conspicuous "powered by IKanoon" attribution, explicitly including RAG context and fine-tuning; terms silent on caching and bulk storage ([docs](https://api.indiankanoon.org/documentation/) · [pricing](https://api.indiankanoon.org/pricing/) · [terms](https://api.indiankanoon.org/terms/)) | **Lookup, fragment search and citator seed**; not bulk storage until confirmed in writing |
| **eCourts judgment portal** (`judgments.ecourts.gov.in`) | Full-text search of SC and HC judgments | Web with arithmetic CAPTCHA; no API | Public judicial record | On-demand fallback, phase 1 |
| **OpenNyAI datasets and models** | Rhetorical roles (13 labels), legal NER with PRECEDENT and STATUTE entities | GitHub / Hugging Face | Code Apache-2.0; data CC-BY-SA-4.0 ([roles](https://github.com/Legal-NLP-EkStep/rhetorical-role-baseline) · [NER](https://github.com/Legal-NLP-EkStep/legal_NER)) | Training data and citation detection |
| **LegalSeg** | 7,120 Indian judgments, 1.49M sentences with rhetorical roles (2025) | GitHub | Research release ([repo](https://github.com/ShubhamKumarNigam/LegalSeg)) | Training data for the role classifier |
| **Manupatra, SCC Online, AIR** | Proprietary reporters with editorial headnotes and citators | Subscription, no developer API; terms prohibit storing or reproducing content in other retrieval systems ([Manupatra terms](https://www.manupatrafast.com/reg/terms.pdf)) | Proprietary | **Not used.** Phase 2 bring-your-own-login lookups only, using the user's own session |
| **IL-TUR** | Indian legal benchmark suite | Hugging Face | CC-BY-NC-SA-4.0 | **Not used** (non-commercial) |

**The paragraph-numbering problem.** Whether SCC paragraph numbers match AIR, SCR or the official text is disputed in the literature ([one view](https://niyam.ai/blog/how-to-cite-indian-judgments) · [another](https://www.barandbench.com/news/ending-citation-chaos-neutral-citation-simplifies-legal-referencing-in-indian-courts)); older and originally unnumbered judgments were numbered by editors, and the Supreme Court's April 2023 direction that all courts number paragraphs is prospective practice, not a rule ([Verdictum](https://www.verdictum.in/court-updates/supreme-court/supreme-court-asks-all-courts-and-tribunals-to-number-paragraphs-1471837)). OrderOrder therefore assigns its own canonical paragraph IDs anchored to the official text, records the text version behind every pinpoint, and maintains a per-reporter mapping where it can be established. The Princeton benchmark identified inconsistent pagination in public databases as the hard ceiling on pincite verification; this is a first-class design item, not a footnote.

---

## 12. Success metrics

### 12.1 Engine metrics (measured on the gold set, see [ARCHITECTURE.md](ARCHITECTURE.md) §11)

| Metric | Hackathon target | Phase 1 target |
|---|---|---|
| Fabrication recall (modes 1-2 caught) | ≥ 99% | ≥ 99.5% |
| Pinpoint hit@1 / hit@3 | ≥ 70% / ≥ 85% | ≥ 85% / ≥ 92% |
| Support-level macro-F1 (full / partial / none / contradicted) | ≥ 0.70 | ≥ 0.80 |
| Overstatement recall (modes 8-9) | ≥ 70% | ≥ 85% |
| Voice / opinion attribution accuracy | ≥ 85% | ≥ 92% |
| Treatment detection recall (mode 10) | ≥ 80% | ≥ 90% |
| Quote-grounding rate | 100% | 100% |
| Abstention rate ("needs review") | ≤ 20% | ≤ 10% |
| Median latency per citation (batched, judgment already digested) | ≤ 30 s | ≤ 10 s |

### 12.2 Product metrics (phase 1 onward)

- Briefs verified per week; citations per brief; share of citations graded C or worse (the "catch rate").
- User-confirmed catches: verdicts the user marked "this was a real problem".
- Verdict overrides: verdicts the user marked wrong (feeds the gold set).
- Draft propositions accepted without edit.
- Weekly active mooters in the launch college; number of moot societies onboarded.

### 12.3 Hackathon demo success

The demo memorial's eight citations produce the eight expected verdicts, each with a highlighted paragraph and a memo; the drafting flow exports a DOCX with a verification appendix; the whole run completes on the demo box in under ten minutes.

---

## 13. Competitive landscape

| Product | What it does | Public pricing | Verifies extent of support against judgment text? |
|---|---|---|---|
| **Manupatra AI Search** | Natural-language answers with sources; flags overruled judgments; Case Map with negative treatment ([site](https://www.manupatra.ai/legal-research)) | AI Summary ₹5,000-10,000/yr; credit wallets ₹6,000-12,000 | Citator-style flags only |
| **SCC Online AI Pro** (preview Feb 2026) | Issue-law-application-conclusion answers over SCC's licensed database ([launch](https://www.scconline.com/blog/post/2026/02/19/scc-online-ai-pro-preview-launch-new-delhi/)) | Not public | Grounded answers; no pinpoint or extent check claimed |
| **Harvey × SCC Online** (Jan 2026) | SCC content as a knowledge source inside Harvey ([announcement](https://www.harvey.ai/blog/harvey-partners-with-scc-online)) | Enterprise | Grounding, not verification |
| **Lexis+ AI / Protégé India** (2026) | Case analysis and workflows; claims built-in verification and citation management | Not public | Unclear; no published accuracy |
| **CaseMine AMICUS** | Generative assistant, precedent discovery | $49-150/month | Source-linked; no verification claim |
| **Jhana.ai**, **Lexlegis.ai**, **Nyaay AI**, **Lucio** | Research and drafting assistants; Nyaay markets itself as "citation-first" | Not public | No published verification benchmark |
| **Clearbrief** (US) | Checks that the source says what the brief claims; links facts to the record | Per seat | Yes, for US law; the closest analogue to OrderOrder |
| **Adalat AI** | Courtroom speech-to-text in 4,000+ courtrooms | n/a | Adjacent, not competing |

**Positioning.** Everyone sells "citation-backed answers". OrderOrder sells the opposite service: it assumes the citation is wrong until proven right, reports existence, location and extent separately, and writes the attack. Ratio-versus-obiter classification and extent-of-support checking have no off-the-shelf model anywhere, in India or abroad; they are a research gap and therefore the moat. Self-hosting is the second differentiator: no incumbent lets a firm keep privileged documents on its own hardware.

---

## 14. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Overstatement detection is genuinely hard; models bluff | High | High | Quote-or-nothing rule; claim decomposition; NLI first pass plus LLM adjudicator; abstention; gold set from day one; report confidence honestly |
| Paragraph numbering differs across reporters | High | High | Canonical paragraph IDs; text-version badge on every pinpoint; per-reporter alignment map; show the user both numbers |
| Corpus text quality (OCR of old scanned judgments) | Medium | Medium | Prefer official born-digital PDFs; PaddleOCR-VL for scans; OCR-derived flag lowers confidence; fuzzy quote match only for OCR text |
| Indian Kanoon terms on caching are unwritten | Medium | Medium | Bulk corpus from AWS Open Data instead; Indian Kanoon lookup-only with attribution; get written confirmation in phase 1 |
| Self-hosted models weaker than frontier cloud models | Medium | Medium | 2026 open models at 27-31B are strong on long-context reading; batching and the digest cache make the 120B-class affordable on one 80 GB card; cloud toggle exists for consenting users |
| The laptop cannot run demo-quality models | Certain | Medium | Free API tiers serve 70B-120B-class open models for the live demo; a free Kaggle or Colab GPU does the batch work; the laptop runs the app and offline development |
| A free tier rate-limits or goes down during the demo | High | Medium | Three providers configured behind LangChain fallbacks; digests precomputed and cached; local Ollama as the last resort; backup video |
| Scope creep between verify and draft | High | Medium | Draft surface reuses the verify engine unchanged; the gate is the only new logic |
| Legal liability / unauthorised practice | Low | High | Research-aid positioning; disclaimers; lawyer remains responsible; no outcome prediction; aligns with draft regulations |
| Privilege waiver through cloud processing | Medium | High | Self-hosted default; cloud toggle requires explicit consent, zero-retention and region check |
| Incumbent adds "verification" marketing | High | Medium | Publish accuracy on an open Indian gold set; be the honest benchmark |

---

## 15. Legal, compliance and ethics

1. **Data protection.** The Digital Personal Data Protection Act 2023 and the DPDP Rules 2025 (notified 14 November 2025) phase in; principal substantive obligations apply from around May 2027 ([PIB](https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf)). There is no blanket localisation mandate, but the Government may restrict transfers by notification ([SFLC](https://sflc.in/dpdp-rules-2025-significant-data-fiduciaries-and-data-transfers/)). OrderOrder processes in India by default, minimises personal data, supports deletion, and keeps an audit log.
2. **Privilege.** Advocate-client communications are protected under sections 132-134 of the Bharatiya Sakshya Adhiniyam 2023; the protection does not extend to salaried in-house counsel ([AZB](https://www.azbpartners.com/bank/legal-privilege-professional-secrecy-in-india/)). Sending a client brief to a third-party model without consent is a waiver risk; hence self-hosting by default in production and an explicit consent step for the cloud toggle. The hackathon build runs on free cloud tiers, which is acceptable only because it processes moot memorials and synthetic matters, never client documents.
3. **Professional conduct.** Following *Pooja Ramesh Singh* the advocate remains responsible for every citation filed. OrderOrder's outputs say so on every page and never present a verdict as legal advice.
4. **Court AI policies.** Kerala HC's 2025 policy and the Supreme Court's 2026 draft regulations permit assistive uses including citation verification, require human verification, and bar AI adjudication. OrderOrder is designed inside those lines and will track the final regulations.
5. **Naming and marketing.** The product is OrderOrder, from the courtroom call to order; the repository is `order-order`. Still outstanding before launch: a trademark search, a domain, and a check that marketing to advocates does not trip Bar Council of India rules on advertising by advocates (the product markets itself, not any advocate).
6. **Attribution.** Indian Kanoon attribution wherever its data appears or feeds retrieval; CC-BY attribution for the AWS Open Data datasets in the app footer and documentation.
7. **No training on user data.** User documents never train or fine-tune any model. Gold-set contributions are opt-in and anonymised.

---

## 16. Scope and phasing

| Phase | Window | Scope | Exit criterion |
|---|---|---|---|
| **0. Hackathon MVP** | 10 working days (compressible) | SC-only subset corpus; Surface A for modes 1, 2, 4, 5, 6, 8, 10, 12; Surface B for one matter type with the gate; DOCX export; minimal UI; 50-claim gold set; ₹0 stack on free tiers | Demo script runs end to end on the laptop against free tiers |
| **1. Foundation** | Months 1-3 after | Full SC corpus; own citator graph; retrained role classifier; 2-3 High Courts; gold set 500+; teams; Word add-in spike; Indian Kanoon written terms | Phase-1 metric targets met; 3 moot societies onboarded |
| **2. Practitioner product** | Months 4-9 | BYO-login connectors; moot-court mode; pricing and billing; DPDP-ready handling; on-prem package | Paying practitioners; firm pilot |
| **3. Coverage** | Months 10-18 | All High Courts; tribunals; statutes and amendments; statutory-provision verification; regional-language OCR | — |

Detail in [ROADMAP.md](ROADMAP.md).

---

## 17. Open questions

| Question | Owner | Needed by |
|---|---|---|
| Hackathon date and format (demo length, judging criteria) | Developer | Before sprint day 1 |
| Which moot memorials can be used for the gold set and demo (permissions from authors) | Co-founder | Sprint day 3 |
| Indian Kanoon's position on caching fetched documents, in writing | Developer | Phase 1 |
| Whether Gemma 4's licence permits commercial use as the research pass reported (re-verify) | Developer | Before model choice |
| Empirical check of SCC vs official paragraph numbering on a 50-judgment sample | Co-founder | Phase 1 |
| Trademark search and domain for the OrderOrder name | Both | Before public launch |

---

## 18. Glossary

| Term | Meaning |
|---|---|
| **Ratio decidendi** | The legal principle necessary to the decision; the binding part of a judgment |
| **Obiter dicta** | Observations not necessary to the decision; persuasive only |
| **Pinpoint / pincite** | The paragraph (or page) of a judgment that a citation refers to |
| **Neutral citation** | Court-assigned, reporter-independent citation, e.g. `2024 INSC 407` (Supreme Court) or `2023:DHC:2720` (Delhi HC) |
| **Parallel citations** | The same judgment's citations in different reporters (SCC, AIR, SCR, SCALE, JT) |
| **Headnote** | Editorial summary at the top of a reported judgment; not part of the judgment |
| **Coram / bench strength** | The judges who decided a case and how many; larger benches bind smaller ones |
| **Per incuriam** | A decision given in ignorance of binding authority; weakened precedential value |
| **Overruled / distinguished / followed** | Subsequent treatment of a precedent by later courts |
| **Written submission** | The written argument filed before oral hearing; in moots, the memorial |
| **Memorial** | A moot-court team's written submission |
| **Article 141** | Constitution of India: law declared by the Supreme Court binds all courts |
| **SCR / SCC / AIR** | Supreme Court Reports (official); Supreme Court Cases and All India Reporter (private reporters) |
| **Text version** | The specific source text of a judgment (official PDF, AWS Open Data copy, Indian Kanoon copy) against which a pinpoint was resolved |

---

## 19. Sources

Research for this document was carried out on 4 September 2026. Load-bearing claims (the July 2026 Supreme Court judgment, the draft AI regulations, both AWS Open Data licences, Indian Kanoon pricing and terms, the PaddleOCR-VL licence) were re-fetched from primary pages the same day. All URLs are inline above; tooling sources are in [TECH_STACK.md](TECH_STACK.md).
