"""Stake for the Holotable.

Signed cards. End a turn as close to zero as you can.
See README for the house rules.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Optional, Union

StakeCard = Union[int, str]  # int values; "NULL" is 0

BOMB_LIMIT = 23  # bust if abs(total) > 23
TARGET = 100  # first to this match score wins
OPENING_CARDS = 2


def create_stake_deck() -> List[StakeCard]:
    """−10..−1 and +1..+10 (two each) + two Nulls (0)."""
    deck: List[StakeCard] = []
    for n in range(1, 11):
        deck.extend([n, n, -n, -n])
    deck.extend(["NULL", "NULL"])
    return deck


def shuffle_stake(deck: List[StakeCard], rng: random.Random | None = None) -> None:
    (rng or random).shuffle(deck)


def card_value(card: StakeCard) -> int:
    if card == "NULL":
        return 0
    return int(card)


def hand_total(hand: List[StakeCard]) -> int:
    return sum(card_value(c) for c in hand)


def is_bomb(hand: List[StakeCard]) -> bool:
    return abs(hand_total(hand)) > BOMB_LIMIT


def stand_points(hand: List[StakeCard]) -> int:
    """Score for a non-bust stand: 24 − |total| (exact 0 / Pure Stake = 24)."""
    total = hand_total(hand)
    return 24 - abs(total)


def display_stake_card(card: StakeCard) -> str:
    if card == "NULL":
        return "Null"
    if isinstance(card, int):
        return f"{card:+d}" if card != 0 else "0"
    return str(card)


@dataclass
class StakePlayer:
    name: str
    score: int = 0


@dataclass
class StakeTurnResult:
    points: int
    busted: bool = False
    pure: bool = False  # exact 0
    hand: List[StakeCard] = field(default_factory=list)
    total: int = 0
    log: List[str] = field(default_factory=list)


class StakeGame:
    """Match state: deck, seats, race to TARGET."""

    TARGET = TARGET
    BOMB_LIMIT = BOMB_LIMIT

    def __init__(self, player_names: List[str], rng: random.Random | None = None):
        if not 2 <= len(player_names) <= 4:
            raise ValueError("Stake needs 2–4 players")
        self.rng = rng or random.Random()
        self.players = [StakePlayer(n) for n in player_names]
        self.deck: List[StakeCard] = create_stake_deck()
        self.discard: List[StakeCard] = []
        shuffle_stake(self.deck, self.rng)
        self.current = 0

    def _ensure_deck(self, min_cards: int = 1) -> None:
        if len(self.deck) < min_cards:
            self.deck.extend(self.discard)
            self.discard.clear()
            shuffle_stake(self.deck, self.rng)

    def draw(self) -> StakeCard:
        self._ensure_deck()
        return self.deck.pop()

    def _end_hand(self, hand: List[StakeCard], result: StakeTurnResult) -> None:
        self.discard.extend(hand)

    def apply_turn(self, result: StakeTurnResult) -> Optional[StakePlayer]:
        player = self.players[self.current]
        player.score += result.points
        winner = player if player.score >= self.TARGET else None
        self.current = (self.current + 1) % len(self.players)
        return winner


@dataclass
class StakeTurnController:
    """Interactive mid-turn state: opening deal of 2, then hit / stay."""

    game: StakeGame
    hand: List[StakeCard] = field(default_factory=list)
    log: List[str] = field(default_factory=list)
    result: Optional[StakeTurnResult] = None
    last_card: Optional[StakeCard] = None
    started: bool = False

    @property
    def done(self) -> bool:
        return self.result is not None

    @property
    def turn_score(self) -> int:
        """Potential stand points if not busted; 0 if bomb."""
        if is_bomb(self.hand):
            return 0
        return stand_points(self.hand)

    @property
    def hand_sum(self) -> int:
        return hand_total(self.hand)

    def start(self) -> Optional[StakeTurnResult]:
        if self.started:
            raise RuntimeError("Turn already started")
        self.started = True
        for _ in range(OPENING_CARDS):
            early = self._draw_one()
            if early:
                return self._finish(early)
        return None

    def hit(self) -> Optional[StakeTurnResult]:
        if self.done:
            raise RuntimeError("Turn already finished")
        if not self.started:
            raise RuntimeError("Turn not started")
        early = self._draw_one()
        if early:
            return self._finish(early)
        return None

    def stay(self) -> StakeTurnResult:
        if self.done:
            raise RuntimeError("Turn already finished")
        if not self.started:
            raise RuntimeError("Turn not started")
        total = hand_total(self.hand)
        if is_bomb(self.hand):
            self.log.append(f"Bomb-out at {total:+d}")
            return self._finish(
                StakeTurnResult(
                    points=0, busted=True, hand=list(self.hand), total=total, log=list(self.log)
                )
            )
        pts = stand_points(self.hand)
        pure = total == 0
        tag = "Pure Stake!" if pure else f"Stand at {total:+d}"
        self.log.append(f"{tag} — bank {pts}")
        return self._finish(
            StakeTurnResult(
                points=pts,
                pure=pure,
                hand=list(self.hand),
                total=total,
                log=list(self.log),
            )
        )

    def _draw_one(self) -> Optional[StakeTurnResult]:
        card = self.game.draw()
        self.last_card = card
        self.hand.append(card)
        label = display_stake_card(card)
        self.log.append(f"Drew {label} (sum {hand_total(self.hand):+d})")
        if is_bomb(self.hand):
            total = hand_total(self.hand)
            self.log.append(f"Bomb-out — |{total}| > {BOMB_LIMIT}")
            return StakeTurnResult(
                points=0, busted=True, hand=list(self.hand), total=total, log=list(self.log)
            )
        return None

    def _finish(self, result: StakeTurnResult) -> StakeTurnResult:
        self.result = result
        self.game._end_hand(self.hand, result)
        return result
