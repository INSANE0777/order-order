# What the demo brief contains, and what the engine says

Ten citations in [brief.txt](brief.txt). Two are sound. Eight are wrong, each in a different way, and
each way is a numbered failure mode from [../docs/PRD.md](../docs/PRD.md) §6. Every judgment cited is
really in the knowledge base and the paragraphs quoted are really its paragraphs, so nothing here is
staged: the errors are planted, the corpus is not.

Every grade below is from a run with **no language model configured**, which is why every row reads
`not_assessed` for support. That column is the one thing a key would change; every finding here is
decided without one.

| # | Citation | Planted | Mode | Engine's verdict |
|---|---|---|---|---|
| 1 | 2019 INSC 770, para 7 | nothing — this is sound | — | **A**, voice `court_majority` |
| 2 | 2019 INSC 770, para 3.2 | counsel's submission cited as the holding | 5 | **D**, "not the court's words (counsel_argument): the passage follows 'It is submitted'" |
| 3 | 2019 INSC 770, para 73 | a paragraph the judgment does not have | 12 | **D**, "the brief cites paragraph 73, but this judgment's numbering stops at 16 (18 paragraphs)" |
| 4 | (2023) 7 SCC 4412 | a case that does not exist | 1 | **F**, "no judgment carries the alias SCC:2023:7:4412" |
| 5 | 2025 INSC 1045, para 29 | words quoted from an earlier judgment (Khet Singh), cited as this Court's | 5 | **D**, voice `quoted_precedent` |
| 6 | Narcotics Control Bureau v. Kashif, (2025) 3 SCC 118 | real case, invented reporter citation | 2 | **C**, "citation string is wrong … matched on party names instead" |
| 7 | 2024 INSC 1027, para 3 | the High Court's holding cited as the Supreme Court's | 5 | **D**, "the passage follows 'The High Court has vide the impugned judgement held'" |
| 8 | 2024 INSC 1027, para 17 | a quotation stopped before its "unless" clause | 9 | **C**, "the brief quotes the court as far as '…public interest jurisdiction,' and stops; the sentence continues 'unless the court is satisfied that the party has not approached it with clean hands'" |
| 9 | 2024 INSC 1051, para 18 | nothing — this is sound | — | **A**, voice `court_majority` |
| 10 | 2019 INSC 770, para 7 | a two-judge decision called a Constitution Bench | 3 | **D**, "the brief calls this 'Constitution Bench', which is 5 judges; the judgment was decided by 2" |

Citation 3 draws a second finding: the paragraph the brief pinpointed cannot be located, and among the
candidates is one whose printed number breaks the judgment's sequence, which is what a block quoted
from another judgment looks like.

Citation 6 resolves by party name because the reporter citation matches nothing, which is the honest
answer: the case exists, the citation string does not.

Citation 8 is the one worth pausing on. Every word the brief quotes is the court's, in order, exactly.
The brief did not misquote and did not invent; it stopped. What it stopped before reverses the
proposition in the only case where the point arises, and finding it needs no model — only a string
comparison against the sentence the words came from.

## What is not demonstrated here

- **Mode 6 (dissent).** None of the eleven judgments ingested so far carries a dissent, so there is no
  honest way to show it against real data. The path is covered end to end in `tests/test_graph.py`.
- **Modes 4, 7 and 8 (not there, obiter as ratio, overstatement).** These turn on what a passage
  *means* and need a model. Run `demo/scripted_model.py` to see the comparator and the quote check
  working on real judgment text with the model's answer supplied from a script.
- **Mode 10 (dead law).** The citator is built and holds 8,716 edges, but none of the judgments this
  brief cites has been negatively treated by a judgment the corpus holds. `orderorder treatment
  INSC:2014:53` shows the check working, on a judgment a Constitution Bench overruled in 2020.
- **Mode 11 (distinguishable).** Needs the facts of the matter before the court, which no brief
  supplies on its own: `orderorder verify --file brief.txt --facts matter.txt`. It also needs a model.
