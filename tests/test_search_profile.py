from __future__ import annotations

import textwrap

from scraper.filters import DEFAULT_INCLUDE_KEYWORDS, is_eligible, rank
from scraper.search_profile import SearchProfile, load_profile
from tests.test_filters import make_job


def test_load_profile_missing_file_returns_defaults(tmp_path):
    p = load_profile(tmp_path / "nope.toml")
    assert p == SearchProfile()
    assert p.role == "SDET / Automation QA"
    assert p.include_keywords == DEFAULT_INCLUDE_KEYWORDS
    assert p.eligibility_enabled is True


def test_load_profile_full_file(tmp_path):
    f = tmp_path / "search.toml"
    f.write_text(textwrap.dedent("""
        [search]
        role = "Data Engineer"
        include_keywords = ["data engineer", "etl", "airflow"]
        exclude_keywords = ["intern"]

        [eligibility]
        enabled = true
        eligible_regions = ["worldwide", "united states", "usa"]
        blocked_regions = ["india"]
        block_us_states = false
        prioritize = ["united states", "remote"]
    """))
    p = load_profile(f)
    assert p.role == "Data Engineer"
    assert p.include_keywords == ("data engineer", "etl", "airflow")
    assert p.exclude_keywords == ("intern",)
    assert p.eligible_regions == ("worldwide", "united states", "usa")
    assert p.blocked_regions == ("india",)
    assert p.block_us_states is False
    assert p.prioritize == ("united states", "remote")


def test_load_profile_partial_file_falls_back_per_key(tmp_path):
    f = tmp_path / "search.toml"
    f.write_text('[search]\nrole = "Backend Engineer"\n')
    p = load_profile(f)
    assert p.role == "Backend Engineer"
    # Unspecified keys keep their defaults.
    assert p.include_keywords == DEFAULT_INCLUDE_KEYWORDS
    assert p.eligibility_enabled is True


def test_us_based_profile_keeps_us_and_drops_elsewhere():
    # A US-based user's region lists invert the shipped default.
    us_eligible = ("worldwide", "anywhere", "remote", "united states", "usa")
    us_blocked = ("india", "europe", "asia")
    us_job = make_job(title="QA Engineer", tags=[], locations=["Austin, TX, United States"])
    eu_job = make_job(title="QA Engineer", tags=[], locations=["Berlin, Germany europe"])
    assert is_eligible(
        us_job, eligible_regions=us_eligible, blocked_regions=us_blocked, block_us_states=False
    ) is True
    assert is_eligible(
        eu_job, eligible_regions=us_eligible, blocked_regions=us_blocked, block_us_states=False
    ) is False


def test_block_us_states_toggle():
    j = make_job(title="QA Engineer", locations=["San Francisco, CA"])
    assert is_eligible(j, block_us_states=True) is False
    # With the toggle off and no other blocked token, the bare state code is kept.
    assert is_eligible(j, block_us_states=False) is True


def test_rank_custom_prioritize_floats_chosen_region_first():
    older_us = make_job(title="QA A", company="A", locations=["New York"], tags=["united states"])
    newer_apac = make_job(title="QA B", company="B", locations=["Singapore"], tags=[])
    out = rank([newer_apac, older_us], prioritize=["united states", "new york"])
    assert out[0].company == "A"  # US-prioritized wins despite the other being APAC
