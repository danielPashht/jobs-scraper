"""LinkedIn query/location expansion — pure config logic, no HTTP."""

from __future__ import annotations

from scraper.boards.linkedin import DEFAULT_KEYWORDS, DEFAULT_LOCATION, LinkedInBoard


def test_locations_default_to_worldwide():
    assert LinkedInBoard()._locations() == (DEFAULT_LOCATION,)


def test_locations_come_from_board_options():
    """A Cyrillic query only returns results when pinned to a country."""
    board = LinkedInBoard(options={"locations": ["Kazakhstan", "Cyprus"]})
    assert board._locations() == ("Kazakhstan", "Cyprus")


def test_keywords_query_is_ored_and_falls_back():
    assert LinkedInBoard()._keywords_query() == DEFAULT_KEYWORDS
    board = LinkedInBoard(keywords=["менеджер проект", "project manager"])
    assert board._keywords_query() == '"менеджер проект" OR "project manager"'


def test_request_budget_defaults_and_validates(caplog):
    assert LinkedInBoard()._max_requests() == 12
    assert LinkedInBoard(options={"max_requests": 4})._max_requests() == 4
    assert LinkedInBoard(options={"max_requests": 0})._max_requests() == 1
    with caplog.at_level("WARNING"):
        assert LinkedInBoard(options={"max_requests": "lots"})._max_requests() == 12
    assert "bad max_requests" in " ".join(r.getMessage() for r in caplog.records)


def test_fetch_stops_at_the_request_budget(monkeypatch):
    """4 locations × 3 pages would be 12 requests; a budget of 2 must cut it."""
    calls: list[str] = []

    class FakeResp:
        status_code = 200
        text = "<ul><li></li></ul>"  # one unparseable card → location exhausted

        def raise_for_status(self):
            return None

    board = LinkedInBoard(
        options={"locations": ["KZ", "CY", "GE", "UZ"], "max_requests": 2},
        keywords=["project manager"],
    )
    monkeypatch.setattr(
        board.client, "get", lambda url, params=None: calls.append(params["location"]) or FakeResp()
    )
    monkeypatch.setattr("scraper.boards.linkedin.time.sleep", lambda _s: None)

    assert list(board.fetch(max_pages=3)) == []
    assert calls == ["KZ", "CY"]  # stopped at the budget, one page each
    board.close()
