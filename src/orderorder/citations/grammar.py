"""Citation grammar for Indian case law.

Recognises the reporter formats a brief can contain, the neutral citations of the Supreme Court and the
High Courts, Indian Kanoon document URLs, and the pinpoint attached to a citation. Every match is
normalised to an alias key such as `SCC:2019:4:1`, `AIR:SC:1973:1461`, `INSC:2024:407` or
`NC:DHC:2023:2720`, which is what `citation_alias.normalized` stores and the resolver looks up.

No open-source Indian citation parser exists; this module is the build-not-buy item from the tech stack.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from orderorder.citations.hc_prefixes import court_for_prefix

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Pinpoint:
    kind: str  # "para" | "page"
    start: int
    end: int | None = None
    raw: str = ""

    @property
    def label(self) -> str:
        if self.end and self.end != self.start:
            return f"{self.start}-{self.end}"
        return str(self.start)


@dataclass
class Citation:
    kind: str  # reporter | neutral | hc_neutral | indiankanoon
    reporter: str  # SCC, SCC-CRI, SCCONLINE, AIR, SCR, SCALE, JT, INSC, NC, IK
    raw: str
    span: tuple[int, int]
    normalized: str
    year: int | None = None
    volume: int | None = None
    page: int | None = None
    court: str | None = None  # court code inside the citation (SC, Del, DHC, ...)
    suffix: str | None = None  # e.g. DB for a division bench
    pinpoint: Pinpoint | None = None
    party_names: str | None = None
    extras: dict = field(default_factory=dict)

    @property
    def is_supreme_court(self) -> bool:
        if self.reporter in {"SCC", "SCC-CRI", "SCC-CIV", "SCC-LS", "SCR", "SCALE", "JT", "INSC"}:
            return True
        if self.reporter == "AIR" and (self.court or "").upper() in {"SC", "SCW"}:
            return True
        return self.reporter == "SCCONLINE" and (self.court or "").upper() == "SC"


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_YEAR = r"(?P<year>19[5-9]\d|20[0-4]\d)"
_SP = r"[\s ]*"

# (2019) 4 SCC 1 | (2019) 4 SCC (Cri) 1 | 2019 (4) SCC 1 | (2019) 4 SCC 1, para 23
SCC_RE = re.compile(
    rf"\(?{_YEAR}\)?{_SP}\(?(?P<vol>\d{{1,3}})\)?{_SP}S\.?C\.?C\.?{_SP}"
    rf"(?:\((?P<series>Cri|Civ|L&S|LS|Cr)\){_SP})?(?:Supp{_SP})?(?P<page>\d{{1,5}})\b",
    re.IGNORECASE,
)

# 2026 SCC OnLine SC 1258 | 2019 SCC OnLine Del 1234
SCC_ONLINE_RE = re.compile(
    rf"{_YEAR}{_SP}S\.?C\.?C\.?{_SP}On{_SP}?Line{_SP}(?P<court>[A-Z][A-Za-z&]{{0,8}})?{_SP}(?P<page>\d{{1,6}})\b",
    re.IGNORECASE,
)

# AIR 1973 SC 1461 | AIR 2019 SCW 123 | AIR 2019 SUPREME COURT 1234 | AIR 2019 Del 12 | AIR OnLine 2019 SC 123
AIR_RE = re.compile(
    rf"A\.?I\.?R\.?{_SP}(?:OnLine{_SP})?{_YEAR}{_SP}(?P<court>SUPREME{_SP}COURT|[A-Z][A-Za-z&]{{0,10}}){_SP}(?P<page>\d{{1,6}})\b",
    re.IGNORECASE,
)

# [2019] 4 SCR 1 | (2019) 4 SCR 1 | 2019 (4) SCR 1 | [2023] 1 S.C.R. 1
SCR_RE = re.compile(
    rf"[\[(]?{_YEAR}[\])]?{_SP}\(?(?P<vol>\d{{1,3}})\)?{_SP}S\.?C\.?R\.?{_SP}(?P<page>\d{{1,5}})\b",
    re.IGNORECASE,
)

# 2019 (4) SCALE 1 | (2019) 4 SCALE 1
SCALE_RE = re.compile(
    rf"\(?{_YEAR}\)?{_SP}\(?(?P<vol>\d{{1,3}})\)?{_SP}SCALE{_SP}(?P<page>\d{{1,5}})\b",
    re.IGNORECASE,
)

# JT 2019 (4) SC 1 | 2019 (4) JT 1
JT_RE = re.compile(
    rf"(?:J\.?T\.?{_SP}{_YEAR}{_SP}\((?P<vol>\d{{1,3}})\){_SP}(?:SC{_SP})?(?P<page>\d{{1,5}})"
    rf"|(?P<year2>19[5-9]\d|20[0-4]\d){_SP}\((?P<vol2>\d{{1,3}})\){_SP}J\.?T\.?{_SP}(?P<page2>\d{{1,5}}))\b",
    re.IGNORECASE,
)

# 2024 INSC 407
INSC_RE = re.compile(rf"{_YEAR}{_SP}INSC{_SP}(?P<num>\d{{1,5}})\b", re.IGNORECASE)

# 2023:DHC:2720 | 2023:DHC:2073-DB | 2023:KHC-D:12 | 2023/MHC/1234
HC_NEUTRAL_RE = re.compile(
    rf"\b{_YEAR}[:/](?P<prefix>[A-Z]{{2,6}}(?:-[A-Z]{{1,4}})?)[:/](?P<num>\d{{1,7}})(?:-(?P<suffix>[A-Z]{{1,3}}))?\b"
)

# indiankanoon.org/doc/12345/
IK_RE = re.compile(r"indiankanoon\.org/doc/(?P<doc>\d+)/?", re.IGNORECASE)

# para 23 | paras 23-25 | paragraph 12 to 14 | at para 23 | ¶ 23 | [23]
PINPOINT_RE = re.compile(
    r"(?:,|;|\s|at)\s*(?:\(?(?:at\s+)?(?:para(?:graph)?s?\.?|¶)\s*(?P<p1>\d{1,4})"
    r"(?:\s*(?:-|–|—|to|and)\s*(?P<p2>\d{1,4}))?\)?"
    r"|\[(?P<b1>\d{1,4})\](?:\s*(?:-|–|to)\s*\[?(?P<b2>\d{1,4})\]?)?"
    r"|(?:at\s+)?(?:p|pp|page|pages)\.?\s*(?P<g1>\d{1,5})(?:\s*(?:-|–|to)\s*(?P<g2>\d{1,5}))?)",
    re.IGNORECASE,
)

# Party names immediately before a citation: "Kesavananda Bharati v. State of Kerala, (1973) 4 SCC 225"
PARTIES_RE = re.compile(
    r"(?P<a>[A-Z][A-Za-z0-9.&'()\-]*(?:\s+(?:of|and|the|&|[A-Z][A-Za-z0-9.&'()\-]*)){0,9})"
    r"\s+(?:v\.?|vs\.?|versus)\s+"
    r"(?P<b>[A-Z][A-Za-z0-9.&'()\-]*(?:\s+(?:of|and|the|&|[A-Z][A-Za-z0-9.&'()\-]*)){0,9})"
)

_REPORTER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("SCCONLINE", SCC_ONLINE_RE),  # before SCC so "SCC OnLine" is not read as "SCC"
    ("SCC", SCC_RE),
    ("AIR", AIR_RE),
    ("SCR", SCR_RE),
    ("SCALE", SCALE_RE),
    ("JT", JT_RE),
    ("INSC", INSC_RE),
    ("NC", HC_NEUTRAL_RE),
    ("IK", IK_RE),
]

# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def _court_code(raw: str | None) -> str | None:
    if not raw:
        return None
    r = re.sub(r"\s+", " ", raw.strip()).upper()
    if r in {"SUPREME COURT", "S.C.", "SC"}:
        return "SC"
    r = r.replace(".", "")
    return r


def normalize_alias(reporter: str, **parts: object) -> str:
    """Build the canonical alias key. Argument order is fixed per reporter so keys are comparable."""
    reporter = reporter.upper()
    if reporter in {"SCC", "SCC-CRI", "SCC-CIV", "SCC-LS", "SCR", "SCALE", "JT"}:
        return f"{reporter}:{parts['year']}:{parts['volume']}:{parts['page']}"
    if reporter == "SCCONLINE":
        return f"SCCONLINE:{parts.get('court') or 'SC'}:{parts['year']}:{parts['page']}"
    if reporter == "AIR":
        return f"AIR:{parts.get('court') or 'SC'}:{parts['year']}:{parts['page']}"
    if reporter == "INSC":
        return f"INSC:{parts['year']}:{parts['number']}"
    if reporter == "NC":
        key = f"NC:{str(parts['prefix']).upper()}:{parts['year']}:{int(parts['number'])}"
        return key + (f"-{str(parts['suffix']).upper()}" if parts.get("suffix") else "")
    if reporter == "IK":
        return f"IK:{parts['doc']}"
    raise ValueError(f"unknown reporter {reporter}")


def normalize_citation_string(text: str) -> str | None:
    """Normalise a bare citation string ("(2019) 4 SCC 1") to its alias key, or None if unparseable."""
    c = parse_citation(text)
    return c.normalized if c else None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _build(reporter: str, m: re.Match[str], text: str) -> Citation | None:
    g = m.groupdict()
    raw = m.group(0).strip()
    span = (m.start(), m.end())
    try:
        if reporter == "SCC":
            series = (g.get("series") or "").upper().replace(".", "")
            rep = {"CRI": "SCC-CRI", "CR": "SCC-CRI", "CIV": "SCC-CIV", "L&S": "SCC-LS", "LS": "SCC-LS"}.get(
                series, "SCC"
            )
            year, vol, page = int(g["year"]), int(g["vol"]), int(g["page"])
            return Citation(
                "reporter",
                rep,
                raw,
                span,
                normalize_alias(rep, year=year, volume=vol, page=page),
                year=year,
                volume=vol,
                page=page,
                court="SC",
            )
        if reporter == "SCCONLINE":
            court = _court_code(g.get("court")) or "SC"
            year, page = int(g["year"]), int(g["page"])
            return Citation(
                "reporter",
                "SCCONLINE",
                raw,
                span,
                normalize_alias("SCCONLINE", court=court, year=year, page=page),
                year=year,
                page=page,
                court=court,
            )
        if reporter == "AIR":
            court = _court_code(g.get("court")) or "SC"
            year, page = int(g["year"]), int(g["page"])
            return Citation(
                "reporter",
                "AIR",
                raw,
                span,
                normalize_alias("AIR", court=court, year=year, page=page),
                year=year,
                page=page,
                court=court,
            )
        if reporter in {"SCR", "SCALE"}:
            year, vol, page = int(g["year"]), int(g["vol"]), int(g["page"])
            return Citation(
                "reporter",
                reporter,
                raw,
                span,
                normalize_alias(reporter, year=year, volume=vol, page=page),
                year=year,
                volume=vol,
                page=page,
                court="SC",
            )
        if reporter == "JT":
            year = int(g.get("year") or g.get("year2"))
            vol = int(g.get("vol") or g.get("vol2"))
            page = int(g.get("page") or g.get("page2"))
            return Citation(
                "reporter",
                "JT",
                raw,
                span,
                normalize_alias("JT", year=year, volume=vol, page=page),
                year=year,
                volume=vol,
                page=page,
                court="SC",
            )
        if reporter == "INSC":
            year, num = int(g["year"]), int(g["num"])
            return Citation(
                "neutral",
                "INSC",
                raw,
                span,
                normalize_alias("INSC", year=year, number=num),
                year=year,
                page=num,
                court="SC",
            )
        if reporter == "NC":
            prefix = g["prefix"].upper()
            hc = court_for_prefix(prefix)
            year, num, suffix = int(g["year"]), int(g["num"]), (g.get("suffix") or None)
            return Citation(
                "hc_neutral",
                "NC",
                raw,
                span,
                normalize_alias("NC", prefix=prefix, year=year, number=num, suffix=suffix),
                year=year,
                page=num,
                court=prefix,
                suffix=suffix,
                extras={
                    "court_name": hc.court if hc else None,
                    "bench": hc.bench if hc else None,
                    "prefix_confirmed": bool(hc and hc.confirmed),
                },
            )
        if reporter == "IK":
            return Citation(
                "indiankanoon", "IK", raw, span, normalize_alias("IK", doc=g["doc"]), extras={"doc": g["doc"]}
            )
    except (KeyError, TypeError, ValueError):
        return None
    return None


def parse_citation(text: str) -> Citation | None:
    """Parse the first citation in `text`."""
    found = extract_citations(text)
    return found[0] if found else None


def _attach_pinpoint(c: Citation, text: str) -> None:
    tail = text[c.span[1] : c.span[1] + 40]
    m = PINPOINT_RE.match(tail)
    if not m:
        return
    g = m.groupdict()
    if g.get("p1"):
        c.pinpoint = Pinpoint(
            "para", int(g["p1"]), int(g["p2"]) if g.get("p2") else None, m.group(0).strip(" ,;")
        )
    elif g.get("b1"):
        c.pinpoint = Pinpoint(
            "para", int(g["b1"]), int(g["b2"]) if g.get("b2") else None, m.group(0).strip(" ,;")
        )
    elif g.get("g1"):
        c.pinpoint = Pinpoint(
            "page", int(g["g1"]), int(g["g2"]) if g.get("g2") else None, m.group(0).strip(" ,;")
        )


def _attach_parties(c: Citation, text: str) -> None:
    head = text[max(0, c.span[0] - 160) : c.span[0]]
    best = None
    for m in PARTIES_RE.finditer(head):
        best = m  # keep the last (closest) match
    if best and len(head) - best.end() <= 6:
        c.party_names = f"{best.group('a').strip()} v. {best.group('b').strip()}"


def extract_citations(text: str) -> list[Citation]:
    """Find every citation in `text`, in order of appearance, each with its pinpoint and party names if present.

    Overlapping matches are resolved in favour of the earliest start, then the longest match, so
    "2026 SCC OnLine SC 1258" is one SCC OnLine citation and never also an SCC one.
    """
    matches: list[Citation] = []
    for reporter, pattern in _REPORTER_PATTERNS:
        for m in pattern.finditer(text):
            c = _build(reporter, m, text)
            if c:
                matches.append(c)
    matches.sort(key=lambda c: (c.span[0], -(c.span[1] - c.span[0])))
    kept: list[Citation] = []
    last_end = -1
    for c in matches:
        if c.span[0] < last_end:
            continue
        kept.append(c)
        last_end = c.span[1]
    for c in kept:
        _attach_pinpoint(c, text)
        _attach_parties(c, text)
    return kept
