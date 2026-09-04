"""The citation grammar is the resolver's front door, so its formats are pinned by tests."""

from __future__ import annotations

import pytest

from orderorder.citations.grammar import extract_citations, normalize_citation_string, parse_citation


@pytest.mark.parametrize(
    ("text", "reporter", "normalized"),
    [
        ("(2019) 4 SCC 1", "SCC", "SCC:2019:4:1"),
        ("2019 (4) SCC 1", "SCC", "SCC:2019:4:1"),
        ("(1973) 4 SCC 225", "SCC", "SCC:1973:4:225"),
        ("(2019) 4 S.C.C. 1", "SCC", "SCC:2019:4:1"),
        ("(2019) 4 SCC (Cri) 12", "SCC-CRI", "SCC-CRI:2019:4:12"),
        ("AIR 1973 SC 1461", "AIR", "AIR:SC:1973:1461"),
        ("AIR 2019 SUPREME COURT 1234", "AIR", "AIR:SC:2019:1234"),
        ("A.I.R. 1973 SC 1461", "AIR", "AIR:SC:1973:1461"),
        ("[2019] 9 S.C.R. 593", "SCR", "SCR:2019:9:593"),
        ("(2019) 9 SCR 593", "SCR", "SCR:2019:9:593"),
        ("2019 (4) SCALE 1", "SCALE", "SCALE:2019:4:1"),
        ("JT 2019 (4) SC 1", "JT", "JT:2019:4:1"),
        ("2024 INSC 407", "INSC", "INSC:2024:407"),
        ("2019 INSC 770", "INSC", "INSC:2019:770"),
        ("2026 SCC OnLine SC 1258", "SCCONLINE", "SCCONLINE:SC:2026:1258"),
        ("2023 SCC OnLine Del 1234", "SCCONLINE", "SCCONLINE:DEL:2023:1234"),
        ("2023:DHC:2720", "NC", "NC:DHC:2023:2720"),
        ("2023:DHC:2073-DB", "NC", "NC:DHC:2023:2073-DB"),
        ("2023:KHC-D:12", "NC", "NC:KHC-D:2023:12"),
        ("https://indiankanoon.org/doc/1234567/", "IK", "IK:1234567"),
    ],
)
def test_recognised_formats(text: str, reporter: str, normalized: str) -> None:
    citation = parse_citation(text)
    assert citation is not None, f"grammar missed {text!r}"
    assert citation.reporter == reporter
    assert citation.normalized == normalized


def test_scc_online_is_not_read_as_scc() -> None:
    """'2026 SCC OnLine SC 1258' must not also produce an SCC citation."""
    found = extract_citations("2026 SCC OnLine SC 1258")
    assert len(found) == 1
    assert found[0].reporter == "SCCONLINE"


def test_parallel_citations_all_found() -> None:
    text = "Kesavananda Bharati v. State of Kerala, (1973) 4 SCC 225 : AIR 1973 SC 1461 : [1973] Supp SCR 1"
    found = extract_citations(text)
    reporters = {c.reporter for c in found}
    assert "SCC" in reporters
    assert "AIR" in reporters
    assert found[0].party_names == "Kesavananda Bharati v. State of Kerala"


@pytest.mark.parametrize(
    ("text", "kind", "label"),
    [
        ("(2019) 4 SCC 1, para 23", "para", "23"),
        ("(2019) 4 SCC 1, paras 23-25", "para", "23-25"),
        ("(2019) 4 SCC 1 at paragraph 12", "para", "12"),
        ("(2019) 4 SCC 1, paragraphs 12 to 14", "para", "12-14"),
        ("(2019) 4 SCC 1 [23]", "para", "23"),
        ("(2019) 4 SCC 1, at p. 45", "page", "45"),
        ("(2019) 4 SCC 1, pp. 45-48", "page", "45-48"),
    ],
)
def test_pinpoints(text: str, kind: str, label: str) -> None:
    citation = parse_citation(text)
    assert citation is not None
    assert citation.pinpoint is not None, f"no pinpoint parsed from {text!r}"
    assert citation.pinpoint.kind == kind
    assert citation.pinpoint.label == label


def test_no_pinpoint_when_absent() -> None:
    citation = parse_citation("(2019) 4 SCC 1 was decided in July.")
    assert citation is not None
    assert citation.pinpoint is None


def test_party_names_attach_to_following_citation() -> None:
    citation = parse_citation("As held in Gurmit Singh Bhatia v. Kiran Kant Robinson, (2019) 9 SCR 593")
    assert citation is not None
    assert citation.party_names == "Gurmit Singh Bhatia v. Kiran Kant Robinson"


def test_supreme_court_detection() -> None:
    assert parse_citation("(2019) 4 SCC 1").is_supreme_court
    assert parse_citation("AIR 1973 SC 1461").is_supreme_court
    assert parse_citation("2024 INSC 407").is_supreme_court
    assert not parse_citation("2023:DHC:2720").is_supreme_court
    assert not parse_citation("AIR 2019 Del 12").is_supreme_court


def test_high_court_prefix_metadata() -> None:
    citation = parse_citation("2023:DHC:2720")
    assert citation.extras["court_name"] == "Delhi High Court"
    assert citation.extras["prefix_confirmed"] is True


def test_unknown_hc_prefix_still_parses() -> None:
    """An unrecognised prefix must still normalise so the resolver can try Indian Kanoon."""
    citation = parse_citation("2025:ZZHC:99")
    assert citation is not None
    assert citation.normalized == "NC:ZZHC:2025:99"
    assert citation.extras["court_name"] is None


def test_multiple_citations_in_order_without_overlap() -> None:
    text = "See (2019) 4 SCC 1 and later AIR 1973 SC 1461, and also 2024 INSC 407."
    found = extract_citations(text)
    assert [c.reporter for c in found] == ["SCC", "AIR", "INSC"]
    for a, b in zip(found, found[1:], strict=False):
        assert a.span[1] <= b.span[0]


def test_normalize_citation_string_helper() -> None:
    assert normalize_citation_string("(2019) 4 SCC 1") == "SCC:2019:4:1"
    assert normalize_citation_string("not a citation") is None


def test_rejects_implausible_years() -> None:
    assert parse_citation("(1849) 4 SCC 1") is None
