"""Parsing tests for the Telegram board — fixtures only, no HTTP.

The fixtures mirror the three real post shapes seen on the configured channels:
a full Russian ad (Anastasia's reference vacancy), a link-only post whose role
lives in Telegram's hh.ru link preview, and a post whose title line is split by
an inline link.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from scraper.boards.telegramjobs import TelegramJobsBoard

# The vacancy Anastasia said fits her, as @some_channel would render it.
FULL_AD = """
<div class="tgme_widget_message" data-post="pm_chan/101">
  <div class="tgme_widget_message_text">🚀 Project Manager / Business Analyst<br/>
🌍 Remote<br/>
💰 $2000–2500<br/>
Компания : Startup Studio<br/>
Ищем человека, который станет правой рукой руководителя.<br/>
🔹 Задачи:<br/>
• Построение схем, процессов и workflow (Miro и аналоги)<br/>
• Поддержка порядка в Notion<br/>
• Работа с senior разработчиками команды<br/>
#vacancy #ProjectManager #Notion</div>
  <div class="tgme_widget_message_footer">
    <a class="tgme_widget_message_date" href="https://t.me/pm_chan/101">
      <time datetime="2026-07-24T09:12:00+00:00"></time>
    </a>
  </div>
</div>
"""

# @pm_vacancy: bare hh.ru link, role only in the preview.
LINK_ONLY = """
<div class="tgme_widget_message" data-post="pm_vacancy/56990">
  <div class="tgme_widget_message_text">https://hh.ru/vacancy/135562561</div>
  <a class="tgme_widget_message_link_preview" href="https://hh.ru/vacancy/135562561">
    <div class="link_preview_site_name">hh.ru</div>
    <div class="link_preview_title">Вакансия Руководитель проектов ОКР в Москве, работа в компании Моторика</div>
    <div class="link_preview_description">Зарплата: от 90 000 руб. Москва. Требуемый опыт: 3–6 лет.</div>
  </a>
  <div class="tgme_widget_message_footer">
    <time datetime="2026-07-24T06:00:00+00:00"></time>
  </div>
</div>
"""

# @evacuatejobs: an inline link splits the title line after the preposition.
SPLIT_TITLE = """
<div class="tgme_widget_message" data-post="evacuatejobs/6240">
  <div class="tgme_widget_message_text">Associate General Counsel (Commercial) в<br/>
OrcaBio<br/>
:<br/>
https://www.remocate.app/jobs/x<br/>
Можно работать удалённо.</div>
  <div class="tgme_widget_message_footer">
    <time datetime="2026-07-23T10:00:00+00:00"></time>
  </div>
</div>
"""


def parse(html: str, channel: str = "pm_chan"):
    board = TelegramJobsBoard(options={"channels": [channel]})
    message = BeautifulSoup(html, "html.parser").select_one("div.tgme_widget_message[data-post]")
    return board._parse_message(message, channel, message["data-post"])


def test_full_russian_ad():
    job = parse(FULL_AD)
    assert job.title == "Project Manager / Business Analyst"
    assert job.company == "Startup Studio"
    assert job.salary == "$2000–2500"
    assert job.remote is True  # "Remote" in the body
    assert str(job.url) == "https://t.me/pm_chan/101"
    assert job.posted_at.year == 2026 and job.posted_at.month == 7
    assert "vacancy" in job.tags and "projectmanager" in job.tags and "remote" in job.tags
    # The body is kept for include-matching (Miro/Notion only appear there).
    assert "miro" in job.description.lower()


def test_body_feeds_includes_but_not_excludes():
    """The reference ad mentions "senior разработчиками" — it must still match."""
    from scraper.filters import matches

    job = parse(FULL_AD)
    assert matches(job, ["notion"], ["senior"]) is True
    # An exclude in the *title* still drops it.
    assert matches(job, ["notion"], ["business analyst"]) is False


def test_link_only_post_uses_the_preview():
    job = parse(LINK_ONLY, channel="pm_vacancy")
    assert job.title == "Руководитель проектов ОКР в Москве"
    assert job.company == "Моторика"
    assert job.salary == "от 90 000 руб."
    # Link-only posts point at the real vacancy, not the Telegram message.
    assert str(job.url) == "https://hh.ru/vacancy/135562561"
    assert job.remote is False  # nothing in the ad says remote


def test_split_title_line_is_rejoined():
    job = parse(SPLIT_TITLE, channel="evacuatejobs")
    assert job.title == "Associate General Counsel (Commercial) в OrcaBio"
    assert job.company == "@evacuatejobs"  # no employer label in the post
    assert job.remote is True  # "удалённо"
    assert str(job.url) == "https://t.me/evacuatejobs/6240"


def test_media_only_post_is_skipped():
    html = '<div class="tgme_widget_message" data-post="c/1"></div>'
    assert parse(html, channel="c") is None


def test_channel_handles_are_normalised():
    board = TelegramJobsBoard(
        options={"channels": ["@pm_vacancy", "https://t.me/product_jobs", "remoteit", " "]}
    )
    assert board._channels() == ("pm_vacancy", "product_jobs", "remoteit")


def test_no_channels_configured_yields_nothing(caplog):
    board = TelegramJobsBoard(options={})
    with caplog.at_level("WARNING"):
        assert list(board.fetch(max_pages=1)) == []
    assert "no channels configured" in " ".join(r.getMessage() for r in caplog.records)


def test_queries_prepend_the_plain_feed():
    board = TelegramJobsBoard(options={"channels": ["c"], "queries": ["проект", "аналитик"]})
    assert board._queries() == (None, "проект", "аналитик")
    assert TelegramJobsBoard(options={"channels": ["c"]})._queries() == (None,)


def test_salary_formats():
    salary = TelegramJobsBoard._salary
    assert salary("з/п 70 000–75 000 ₽ после испытательного") == "70 000–75 000 ₽"
    assert salary("Оклад: от 250 000 тенге") == "от 250 000 тенге"
    assert salary("Вилка $3k - $4k на руки") == "$3k - $4k"
    assert salary("Зарплата: не указана") is None


# @rabota_go: label, then a second label, then the actual employer.
DOUBLE_LABEL = """
<div class="tgme_widget_message" data-post="rabota_go/4690">
  <div class="tgme_widget_message_text">Проектный менеджер в видеопродакшн ROX PRO<br/>
Работодатель:<br/>
Компания<br/>
ROX PRO<br/>
— команда, которая раскрывает бренды через видео.<br/>
Удаленка, з/п 70 000–75 000 ₽</div>
  <div class="tgme_widget_message_footer"><time datetime="2026-07-24T08:00:00+00:00"></time></div>
</div>
"""


def test_employer_behind_a_second_label():
    job = parse(DOUBLE_LABEL, channel="rabota_go")
    assert job.title == "Проектный менеджер в видеопродакшн ROX PRO"
    assert job.company == "ROX PRO"
    assert job.salary == "70 000–75 000 ₽"
    assert job.remote is True
