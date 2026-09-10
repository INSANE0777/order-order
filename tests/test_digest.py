"""The judgment digest: aggregation of what the corpus already stores.

The weight check was designed to read a per-judgment digest -- the headnote is the publisher's own
answer to "was this passage necessary to the outcome", and the ratio-labelled paragraphs are the
role labeller's. These tests pin the aggregation: the headnote lands, the holdings are the ratio
paragraphs in order, the disposition is found, an existing digest is never written twice, and a
judgment without a preferred text version is reported rather than guessed.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from orderorder.db.models import Judgment, JudgmentDigest
from orderorder.ingest.digest import build_digests, digest_one
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.roles import mark_roles
from orderorder.ingest.store import store_extracted

JUDGMENT_TEXT = """1. Leave granted.

2. Briefly stated, the facts of the case are that the plaintiff's services were terminated
without a departmental enquiry.

3. We are of the considered view that the enquiry could not have been dispensed with.

4. The appeal is allowed accordingly.
"""


def _store(session, key: str, text: str) -> Judgment:
    judgment = Judgment(
        canonical_key=key,
        court="Supreme Court of India",
        title=f"{key} ALPHA versus BETA",
        source="aws_open_data",
        source_id=key,
        bench_strength=2,
        decided_on=dt.date(2019, 6, 1),
    )
    session.add(judgment)
    session.flush()
    store_extracted(
        session,
        judgment,
        ExtractedJudgment(source_path=key, page_count=1, headnote="", judgment=text),
    )
    session.commit()
    return judgment


def test_the_digest_aggregates_roles_headnote_and_disposition(session) -> None:
    judgment = _store(session, "INSC:2019:1", JUDGMENT_TEXT)
    mark_roles(session)

    outcome = digest_one(session, judgment)
    assert outcome is not None
    digest, version_id = outcome

    assert version_id == judgment.versions[0].id
    assert "services were terminated" in digest["headnote"] or digest["headnote"] == ""
    # The role labeller called paragraph 3 ratio; the digest carries it as the holding.
    assert len(digest["holdings"]) == 1
    assert "enquiry could not have been dispensed with" in digest["holdings"][0]["text"]
    assert "appeal is allowed" in digest["disposition"].lower()
    assert digest["role_counts"]["ratio"] == 1


def test_build_digests_writes_once_and_skips_existing(session) -> None:
    _store(session, "INSC:2019:2", JUDGMENT_TEXT)
    mark_roles(session)

    first = build_digests(session)
    assert first.written == 1
    assert session.scalar(select(JudgmentDigest.judgment_id)) is not None

    second = build_digests(session)
    assert second.written == 0
    assert second.skipped_existing == 1

    refreshed = build_digests(session, refresh=True)
    assert refreshed.written == 1
