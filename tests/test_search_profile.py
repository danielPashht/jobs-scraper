from __future__ import annotations

import textwrap

from scraper.filters import DEFAULT_INCLUDE_KEYWORDS, is_eligible, rank
from scraper.search_profile import (
    DEFAULT_WATCHER,
    SearchProfile,
    load_profile,
    load_profiles,
)
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


def _write_watcher_profile(tmp_path, name: str, boards: str = "") -> object:
    f = tmp_path / f"{name}.toml"
    f.write_text(
        f'[search]\nwatcher = "{name}"\nrole = "BD"\n'
        f'include_keywords = ["business development"]\n{boards}'
    )
    return f


def test_watcher_and_boards_default_to_single_watcher_behaviour(tmp_path):
    p = load_profile(tmp_path / "nope.toml")
    assert p.watcher == DEFAULT_WATCHER
    assert p.boards == ()
    # The default watcher labels its feed by role, not by watcher key.
    assert p.display_name == "SDET / Automation QA"


def test_load_profile_reads_watcher_and_boards(tmp_path):
    f = _write_watcher_profile(tmp_path, "anastasia", boards='boards = ["linkedin"]\n')
    p = load_profile(f)
    assert p.watcher == "anastasia"
    assert p.boards == ("linkedin",)
    assert p.display_name == "anastasia · BD"


def test_board_options_are_loaded_per_board(tmp_path):
    f = tmp_path / "p.toml"
    f.write_text(
        '[search]\nwatcher = "x"\nboards = ["linkedin", "telegram"]\n'
        '[boards.linkedin]\nlocations = ["Kazakhstan", "Cyprus"]\n'
        '[boards.telegram]\nchannels = ["pm_vacancy"]\nmax_requests = 30\n'
        "[boards.broken]\n"
    )
    p = load_profile(f)
    assert p.board_options["linkedin"]["locations"] == ["Kazakhstan", "Cyprus"]
    assert p.board_options["telegram"] == {"channels": ["pm_vacancy"], "max_requests": 30}
    assert p.board_options["broken"] == {}  # empty table is valid, just carries nothing


def test_board_options_default_to_empty(tmp_path):
    assert load_profile(tmp_path / "missing.toml").board_options == {}


def test_load_profiles_returns_one_per_path(tmp_path):
    a = _write_watcher_profile(tmp_path, "ann")
    b = _write_watcher_profile(tmp_path, "bob")
    profiles = load_profiles([a, b, tmp_path / "missing.toml"])
    assert [p.watcher for p in profiles] == ["ann", "bob", DEFAULT_WATCHER]


def test_load_profiles_skips_duplicate_watcher_keys(tmp_path):
    a = _write_watcher_profile(tmp_path, "ann")
    dupe = tmp_path / "ann-copy.toml"
    dupe.write_text('[search]\nwatcher = "ann"\nrole = "Other"\n')
    profiles = load_profiles([a, dupe])
    assert [p.role for p in profiles] == ["BD"]


def test_rank_custom_prioritize_floats_chosen_region_first():
    older_us = make_job(title="QA A", company="A", locations=["New York"], tags=["united states"])
    newer_apac = make_job(title="QA B", company="B", locations=["Singapore"], tags=[])
    out = rank([newer_apac, older_us], prioritize=["united states", "new york"])
    assert out[0].company == "A"  # US-prioritized wins despite the other being APAC
