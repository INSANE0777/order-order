"""The CLI's front door, and the console it prints through.

Two things were only true on the web route and are now true on the command line as well: a brief can
arrive as a PDF or a DOCX rather than only as text, and nothing a judgment or a model says can take
the console down. Rich reads `[...]` in printed text as markup, so a title containing `[/` raised
`MarkupError` *after* the verification had already run -- the worst possible moment to lose the output.
"""

from __future__ import annotations

import io

from typer.testing import CliRunner

from orderorder import cli
from orderorder.db.models import CitationAlias, Judgment

runner = CliRunner()


def _docx(text: str) -> bytes:
    from docx import Document

    document = Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_verify_reads_a_docx_brief(corpus, monkeypatch, tmp_path) -> None:
    """A DOCX on the command line reads the same way it does through /api/upload."""
    monkeypatch.setattr(cli, "get_session", corpus)
    path = tmp_path / "memorial.docx"
    path.write_bytes(_docx("The rule is settled: (2019) 4 SCC 118, para 3."))

    result = runner.invoke(cli.app, ["verify", "--file", str(path), "--no-model"])

    assert result.exit_code == 0, result.output
    assert "(2019) 4 SCC 118" in result.output


def test_a_judgment_title_cannot_break_the_console(corpus, monkeypatch, tmp_path) -> None:
    """Square brackets in corpus text print literally instead of being parsed as Rich markup."""
    monkeypatch.setattr(cli, "get_session", corpus)
    with corpus() as session:
        judgment = Judgment(
            canonical_key="TEST:0002:1",
            court="Supreme Court of India",
            title="ALPHA [/unless] versus BETA",
            source="aws_open_data",
            source_id="TEST:0002:1",
            bench_strength=2,
        )
        session.add(judgment)
        session.flush()
        session.add(
            CitationAlias(
                judgment_id=judgment.id,
                reporter="SCC",
                citation_string="(2020) 1 SCC 1",
                normalized="SCC:2020:1:1",
            )
        )
        session.commit()

    path = tmp_path / "brief.txt"
    path.write_text("See (2020) 1 SCC 1, para 2.", encoding="utf-8")

    result = runner.invoke(cli.app, ["verify", "--file", str(path), "--no-model"])

    assert result.exit_code == 0, result.output
    assert "[/unless]" in result.output


def test_perturb_report_rebuilds_a_table_with_no_model(tmp_path, monkeypatch) -> None:
    """The replay gate: every number comes back from the cache, with no key in the environment."""
    import json

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    rows = []
    for index in range(12):
        rows.append(
            {
                "arm": "verbatim_wrong_paragraph",
                "item_id": f"i{index}",
                "existence": "found",
                "support": "none",
                "quote_verified": False,
                "needs_review": False,
                "findings": [{"mode": 12 if index < 9 else 8, "label": "x"}],
                "error": None,
            }
        )
    cache = tmp_path / "responses.jsonl"
    cache.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    out = tmp_path / "table.txt"

    result = runner.invoke(
        cli.app, ["eval", "perturb", "report", "--cache", str(cache), "--out", str(out)]
    )

    assert result.exit_code == 0, result.output
    text = out.read_text(encoding="utf-8")
    assert "verbatim_wrong_paragraph" in text
    assert "decided catch 75%" in text
    assert "n=12" in text
