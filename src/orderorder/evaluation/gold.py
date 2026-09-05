"""One labelled claim-citation pair, and a file of them.

The shape follows `docs/ARCHITECTURE.md` section 11.1, which aligns with the Princeton LePhantomCite
format so results are comparable, plus the labels this taxonomy needs that theirs does not have.

Two kinds of item live in the same file and the difference matters more than it looks:

  * **planted** — a specific failure mode was introduced deliberately, and the engine is expected to
    find it. These measure recall.
  * **clean** — the citation is sound in every respect, and the engine is expected to say nothing.
    These measure the thing recall cannot see. An engine that flags everything scores perfectly on
    planted items and is useless, because an advocate who is warned about every citation checks none
    of them.

A gold set without clean items is not a gold set; it is a list of things you already knew were wrong.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

# The taxonomy, for readable reports. docs/PRD.md section 6.
MODE_NAMES = {
    1: "phantom",
    2: "mis-cite",
    3: "wrong court or bench",
    4: "not there",
    5: "wrong voice",
    6: "minority opinion",
    7: "obiter as ratio",
    8: "overstatement",
    9: "selective quotation",
    10: "dead or wounded law",
    11: "distinguishable",
    12: "wrong pinpoint",
}


@dataclass
class GoldLabels:
    """What is true about this citation, as opposed to what the brief says about it."""

    exists: bool = True
    judgment_key: str | None = None
    paragraph_label: str | None = None
    support: str | None = None
    voice: str | None = None
    weight: str | None = None
    treatment: str | None = None
    applicability: str | None = None


@dataclass
class GoldItem:
    """One claim and the citation offered for it, with the answer known."""

    id: str
    claim_text: str
    citation_raw: str
    planted_error: int | None = None
    labels: GoldLabels = field(default_factory=GoldLabels)
    source: str = "planted from the corpus"
    user_facts: str | None = None
    annotator: str | None = None
    second_annotator: str | None = None
    notes: str | None = None

    @property
    def is_clean(self) -> bool:
        """No error was planted, so a finding of any kind is a false positive."""
        return self.planted_error is None

    @property
    def mode_name(self) -> str:
        return MODE_NAMES.get(self.planted_error or 0, "clean")

    @property
    def brief_sentence(self) -> str:
        """The sentence as it would appear in a brief: the claim, then the citation."""
        claim = self.claim_text.rstrip(" .")
        return f"{claim}: {self.citation_raw}."

    def as_dict(self) -> dict:
        data = asdict(self)
        data["labels"] = asdict(self.labels)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> GoldItem:
        payload = dict(data)
        payload["labels"] = GoldLabels(**(payload.get("labels") or {}))
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in payload.items() if k in known})


def write_gold(items: list[GoldItem], path: Path) -> int:
    """Write a gold set as JSON Lines, one item per line, so it diffs and appends cleanly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item.as_dict(), ensure_ascii=False) + "\n")
    return len(items)


def read_gold(path: Path) -> list[GoldItem]:
    """Read a gold set. Blank lines are skipped so a hand-edited file still loads."""
    if not path.exists():
        return []
    items: list[GoldItem] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            items.append(GoldItem.from_dict(json.loads(line)))
    return items


def summarise(items: list[GoldItem]) -> dict[str, int]:
    """How many items of each kind, for the report header."""
    counts: dict[str, int] = {}
    for item in items:
        counts[item.mode_name] = counts.get(item.mode_name, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (kv[0] == "clean", kv[0])))
