# OrderOrder

*A self-hosted citation-integrity engine for Indian case law.*

OrderOrder reads a brief, moot-court memorial or written submission, finds every case-law citation, and answers three questions separately for each one: does the case exist, which paragraph is being relied on, and does that paragraph support the proposition **to the extent claimed**. It then writes what opposing counsel would say. The same engine gates a drafting assistant so that nothing enters a written submission that the verifier could not confirm.

It is built on open and official data (AWS Open Data judgments under CC-BY-4.0, the Supreme Court's SCR portal, the Indian Kanoon API with attribution). The hackathon build costs nothing and runs on free tiers with demo data only; in production everything runs on hardware the team controls.

## Documents

| Document | Read it for |
|---|---|
| [docs/PRD.md](docs/PRD.md) | The problem, the evidence that it is urgent, users, the twelve ways a citation lies, requirements for both surfaces, metrics, competition, risks, compliance |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design with nine diagrams: ingestion, the verification engine, the drafting engine, retrieval hierarchy, data model, verdict schema, deployment, evaluation |
| [docs/TECH_STACK.md](docs/TECH_STACK.md) | The zero-cost hackathon stack and the self-hosted production stack, how LangChain and LangGraph are used, free-tier limits and data terms, licence audit, dev-machine setup, bill of materials |
| [docs/ROADMAP.md](docs/ROADMAP.md) | The 10-day hackathon sprint with demo script and cut list, then the startup phases, team split, decision log |

Suggested reading order: PRD §1-6, then ARCHITECTURE §1-4, then TECH_STACK §4, §5 and §12, then ROADMAP §1.

## Status

Documents only. No code yet. Drafted 4 September 2026 for co-founder review.

## Attribution

Judgment data from the [Indian Supreme Court Judgments](https://registry.opendata.aws/indian-supreme-court-judgments/) and [Indian High Court Judgments](https://registry.opendata.aws/indian-high-court-judgments/) datasets on AWS Open Data (CC-BY-4.0). Lookups powered by [IKanoon](https://api.indiankanoon.org/) where indicated.

*OrderOrder is a research aid. The advocate remains responsible for every citation filed.*
