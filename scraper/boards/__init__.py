from scraper.boards.base import Board
from scraper.boards.cryptojobslist import CryptoJobsListBoard
from scraper.boards.linkedin import LinkedInBoard
from scraper.boards.remoteok import RemoteOKBoard
from scraper.boards.telegramjobs import TelegramJobsBoard
from scraper.boards.web3career import Web3CareerBoard
from scraper.boards.weworkremotely import WeWorkRemotelyBoard

ALL_BOARDS: dict[str, type[Board]] = {
    "web3career": Web3CareerBoard,
    "cryptojobslist": CryptoJobsListBoard,
    "remoteok": RemoteOKBoard,
    "weworkremotely": WeWorkRemotelyBoard,
    "linkedin": LinkedInBoard,
    "telegram": TelegramJobsBoard,
}

__all__ = [
    "ALL_BOARDS",
    "Board",
    "CryptoJobsListBoard",
    "LinkedInBoard",
    "RemoteOKBoard",
    "TelegramJobsBoard",
    "Web3CareerBoard",
    "WeWorkRemotelyBoard",
]
