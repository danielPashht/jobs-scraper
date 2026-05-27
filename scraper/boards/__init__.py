from scraper.boards.base import Board
from scraper.boards.cryptojobslist import CryptoJobsListBoard
from scraper.boards.linkedin import LinkedInBoard
from scraper.boards.remoteok import RemoteOKBoard
from scraper.boards.web3career import Web3CareerBoard
from scraper.boards.weworkremotely import WeWorkRemotelyBoard

ALL_BOARDS: dict[str, type[Board]] = {
    "web3career": Web3CareerBoard,
    "cryptojobslist": CryptoJobsListBoard,
    "remoteok": RemoteOKBoard,
    "weworkremotely": WeWorkRemotelyBoard,
    "linkedin": LinkedInBoard,
}

__all__ = [
    "ALL_BOARDS",
    "Board",
    "CryptoJobsListBoard",
    "LinkedInBoard",
    "RemoteOKBoard",
    "Web3CareerBoard",
    "WeWorkRemotelyBoard",
]
