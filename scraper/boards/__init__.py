from scraper.boards.base import Board
from scraper.boards.cryptojobslist import CryptoJobsListBoard
from scraper.boards.web3career import Web3CareerBoard

ALL_BOARDS: dict[str, type[Board]] = {
    "web3career": Web3CareerBoard,
    "cryptojobslist": CryptoJobsListBoard,
}

__all__ = ["ALL_BOARDS", "Board", "CryptoJobsListBoard", "Web3CareerBoard"]
