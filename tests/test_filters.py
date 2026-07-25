from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scraper.filters import (
    deduplicate,
    filter_jobs,
    is_apac_friendly,
    is_eligible,
    is_junk_title,
    is_recent,
    rank,
)
from scraper.models import Job


def make_job(**overrides) -> Job:
    base = {
        "title": "QA Engineer",
        "company": "Acme",
        "source": "web3career",
        "url": "https://example.com/job/1",
        "tags": ["quality assurance", "remote"],
        "locations": ["Remote"],
        "remote": True,
    }
    base.update(overrides)
    return Job(**base)


def test_description_feeds_includes_but_not_excludes():
    """Free-text ads (Telegram) name the role in the body; excludes stay title-scoped."""
    job = make_job(
        title="Правая рука руководителя",
        tags=[],
        locations=[],
        description="Ищем бизнес-аналитика. Работа с senior разработчиками.",
    )
    assert filter_jobs([job], include=["бизнес-аналитик"], exclude=["senior"]) == [job]
    # Same exclude in the title does drop it.
    titled = make_job(title="Senior бизнес-аналитик", tags=[], locations=[])
    assert filter_jobs([titled], include=["бизнес-аналитик"], exclude=["senior"]) == []


def test_include_match_on_title():
    jobs = [
        make_job(title="Senior SDET"),
        make_job(title="Backend Engineer", tags=["python"], locations=[]),
    ]
    out = filter_jobs(jobs)
    assert len(out) == 1
    assert out[0].title == "Senior SDET"


@pytest.mark.parametrize(
    "title",
    [
        "QA Automation Engineer",
        "Sr QA Automation",
        "Senior Mobile Test Automation Engineer",
        "Software Development Engineer in Test",
        "Staff Software Engineer in Test",
    ],
)
def test_include_match_on_common_sdet_title_variants(title):
    # These word orderings were missed by the original keyword list.
    out = filter_jobs([make_job(title=title, tags=[], locations=["Remote"])])
    assert len(out) == 1


def test_exclude_keyword_strips_match():
    jobs = [make_job(title="Manual QA only role")]
    out = filter_jobs(jobs, exclude=["manual qa only"])
    assert out == []


def test_remote_only_filters_non_remote():
    jobs = [
        make_job(title="QA Engineer", remote=True),
        make_job(title="QA Engineer", company="Other", remote=False, tags=["quality assurance"]),
    ]
    out = filter_jobs(jobs, remote_only=True)
    assert len(out) == 1
    assert out[0].company == "Acme"


def test_dedup_same_title_company_case_insensitive():
    jobs = [
        make_job(title="QA Engineer", company="Acme"),
        make_job(title="qa engineer", company="ACME", source="cryptojobslist"),
    ]
    out = deduplicate(jobs)
    assert len(out) == 1
    # First wins.
    assert out[0].source == "web3career"


def test_dedup_keeps_distinct_companies():
    jobs = [
        make_job(company="Acme"),
        make_job(company="Brave"),
    ]
    out = deduplicate(jobs)
    assert len(out) == 2


def test_apac_detection_via_location_and_tags():
    assert is_apac_friendly(make_job(locations=["Singapore"]))
    assert is_apac_friendly(make_job(tags=["remote"]))
    assert not is_apac_friendly(make_job(locations=["New York"], tags=["onsite"]))


def test_rank_puts_apac_friendly_first_then_newest():
    older = make_job(title="QA A", company="A", posted_at=datetime(2026, 1, 1), tags=["remote"])
    newer = make_job(title="QA B", company="B", posted_at=datetime(2026, 5, 1), tags=["onsite"], locations=["NY"])
    out = rank([older, newer])
    assert out[0].title == "QA A"  # APAC-friendly wins despite older date
    assert out[1].title == "QA B"


@pytest.mark.parametrize(
    "title,expected",
    [
        ("SDET Engineer", True),
        ("Automation QA Lead", True),
        ("Frontend Developer", False),
    ],
)
def test_keyword_match_param(title: str, expected: bool):
    jobs = [make_job(title=title, tags=[], locations=[])]
    out = filter_jobs(jobs)
    assert bool(out) is expected


# --- Location eligibility (Asia-based nomad, open to Europe) ---

def test_ineligible_us_country_name():
    j = make_job(tags=["quality assurance"], locations=["New York, United States"])
    assert is_eligible(j) is False


def test_ineligible_us_state_code():
    # The LinkedIn "City, ST" form must be caught even without "United States".
    j = make_job(tags=["quality assurance"], locations=["San Francisco, CA"])
    assert is_eligible(j) is False


def test_ineligible_other_americas():
    j = make_job(tags=["quality assurance"], locations=["São Paulo, Brazil"])
    assert is_eligible(j) is False


def test_eligible_worldwide_marker_overrides_us_location():
    j = make_job(title="QA Lead 100% remote Worldwide", locations=["United States"])
    assert is_eligible(j) is True


def test_eligible_european_relocation():
    j = make_job(tags=["quality assurance"], locations=["Berlin, Germany"])
    assert is_eligible(j) is True


def test_eligible_apac():
    j = make_job(tags=["quality assurance"], locations=["Singapore"])
    assert is_eligible(j) is True


def test_eligible_ambiguous_location_kept():
    # No region signal either way → keep, so we don't miss good jobs.
    j = make_job(tags=["quality assurance"], locations=["Remote"])
    assert is_eligible(j) is True


def test_inc_in_title_does_not_trigger_us_state():
    # ", in" (Indiana) must not match ", Inc" — state codes only match locations.
    j = make_job(title="QA Engineer, Inc growth team", locations=["Remote"])
    assert is_eligible(j) is True


def test_filter_jobs_excludes_ineligible():
    jobs = [
        make_job(title="QA Engineer", company="A", locations=["United States"]),
        make_job(title="QA Engineer", company="B", locations=["Austin, TX"]),
        make_job(title="QA Engineer", company="C", locations=["Remote"]),  # ambiguous
        make_job(title="QA Worldwide", company="D", locations=["United States"]),
        make_job(title="QA Engineer", company="E", locations=["Berlin, Germany"]),
    ]
    out = filter_jobs(jobs, exclude_ineligible=True)
    companies = {j.company for j in out}
    assert companies == {"C", "D", "E"}


# --- Age cutoff ---

def test_is_recent_with_recent_date():
    recent = datetime.now(timezone.utc) - timedelta(days=10)
    assert is_recent(make_job(posted_at=recent), max_age_days=30)


def test_is_recent_drops_old_date():
    old = datetime.now(timezone.utc) - timedelta(days=90)
    assert not is_recent(make_job(posted_at=old), max_age_days=30)


def test_is_recent_unknown_treated_as_recent():
    assert is_recent(make_job(posted_at=None), max_age_days=30)


def test_filter_jobs_drops_old_postings():
    fresh = datetime.now(timezone.utc) - timedelta(days=5)
    stale = datetime.now(timezone.utc) - timedelta(days=120)
    jobs = [
        make_job(title="QA Engineer", company="Fresh", posted_at=fresh),
        make_job(title="QA Engineer", company="Stale", posted_at=stale),
    ]
    out = filter_jobs(jobs, max_age_days=60)
    assert {j.company for j in out} == {"Fresh"}


# --- Junk-title / placeholder filtering ---

@pytest.mark.parametrize(
    "title,expected_junk",
    [
        ("tst", True),
        ("TST", True),
        (" Test ", True),
        ("test job", True),
        ("Test Engineer", False),
        ("Pytest Specialist", False),  # must not catch "tst" as substring
        ("SDET", False),
    ],
)
def test_is_junk_title(title: str, expected_junk: bool):
    assert is_junk_title(title) is expected_junk


def test_filter_jobs_drops_junk_titles_but_keeps_real_qa():
    # Mimics the two real RemoteOK false positives + a legit role.
    jobs = [
        make_job(title="tst", company="Stefanini", tags=["test", "testing", "quality assurance"]),
        make_job(
            title="Expression of Interest SMG Studio",
            company="SMG Studio",
            tags=["game", "testing", "quality assurance"],
        ),
        make_job(title="Test Engineer", company="LegitCo", tags=["quality assurance"]),
    ]
    out = filter_jobs(jobs)
    assert [j.company for j in out] == ["LegitCo"]
