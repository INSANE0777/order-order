"""Quote-or-nothing is the product's central promise, so it is tested hardest.

The rule: a claim can only be "supported" if a verbatim quote is found in the judgment text by string
comparison. These tests pin the normalisation that makes that robust, and pin the refusal to fuzzy-match
born-digital text, which is what stops a model from inventing a near-quote.
"""

from __future__ import annotations

from orderorder.engine.quotes import (
    FUZZY_THRESHOLD,
    MIN_QUOTE_WORDS,
    find_quote,
    normalize,
    verify_quotes,
    word_count,
)

JUDGMENT = (
    "23. The appellant contends that the agreement was void. We are unable to accept that submission. "
    "A misrepresentation vitiates consent only where it induced the contract, and the burden of proving "
    "inducement lies upon the party alleging it."
)


def test_exact_match_returns_offsets_into_the_original() -> None:
    quote = "A misrepresentation vitiates consent only where it induced the contract"
    match = find_quote(quote, JUDGMENT)
    assert match.found
    assert match.match_type == "exact"
    assert JUDGMENT[match.char_start : match.char_end] == quote


def test_curly_quotes_and_dashes_normalise() -> None:
    source = "The court said “the rule is settled” — and it applies here without exception."
    quote = 'The court said "the rule is settled" - and it applies here'
    match = find_quote(quote, source)
    assert match.found
    assert match.match_type == "exact"


def test_whitespace_and_newlines_collapse() -> None:
    source = "A  misrepresentation\n   vitiates\tconsent only where\nit induced the contract."
    quote = "A misrepresentation vitiates consent only where it induced the contract"
    assert find_quote(quote, source).found


def test_case_insensitive() -> None:
    assert find_quote("A MISREPRESENTATION VITIATES CONSENT ONLY WHERE IT INDUCED", JUDGMENT).found


def test_soft_hyphen_and_nbsp_are_ignored() -> None:
    source = "A misrepre­sentation vitiates consent only where it induced the contract."
    assert find_quote("A misrepresentation vitiates consent only where it induced", source).found


def test_absent_quote_is_not_found() -> None:
    match = find_quote("The contract is void ab initio in every circumstance whatsoever", JUDGMENT)
    assert not match.found
    assert match.match_type == "not_found"


def test_born_digital_text_never_fuzzy_matches() -> None:
    """One wrong word must fail on born-digital text. This is what blocks a plausible near-quote."""
    almost = "A misrepresentation vitiates consent whenever it preceded the contract"
    match = find_quote(almost, JUDGMENT, ocr_derived=False)
    assert not match.found


def test_ocr_text_allows_a_close_match() -> None:
    ocr_source = JUDGMENT.replace("vitiates", "vitlates").replace("burden", "burdcn")
    quote = "A misrepresentation vitiates consent only where it induced the contract"
    match = find_quote(quote, ocr_source, ocr_derived=True)
    assert match.found
    assert match.match_type == "fuzzy_ocr"
    assert match.score >= FUZZY_THRESHOLD


def test_short_quotes_are_rejected() -> None:
    match = find_quote("the contract", JUDGMENT)
    assert not match.found
    assert match.match_type == "too_short"
    assert word_count("the contract") < MIN_QUOTE_WORDS


def test_empty_inputs_do_not_crash() -> None:
    assert not find_quote("", JUDGMENT).found
    assert not find_quote("a quote long enough to pass the word count test", "").found


def test_verify_quotes_preserves_order() -> None:
    quotes = [
        "A misrepresentation vitiates consent only where it induced",
        "this sentence is definitely not present in the judgment text",
    ]
    results = verify_quotes(quotes, JUDGMENT)
    assert [r.found for r in results] == [True, False]


def test_normalize_index_map_is_aligned() -> None:
    normalized = normalize("Hello   World")
    assert normalized.text == "hello world"
    assert len(normalized.index_map) == len(normalized.text)
    assert normalized.index_map[0] == 0
