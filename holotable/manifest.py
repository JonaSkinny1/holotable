"""MANIFEST — a goods-bluffing table game for the Holotable.

Locked turn: sell one hand card, name it, buyer pays 2. The buyer may pay 1
to look. No look or a match: the sale stands as named. A miss: the sale fails
and the seller pays the buyer 3 coins, or whatever the seller has.

No action deck. Card faces are data (id + name) so art can replace the label.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

# Face data Jonathan can hang a picture on later. id is stable; name is the label.
GOODS: tuple[dict, ...] = (
    {"id": "helion", "name": "Helion"},
    {"id": "canister", "name": "Plant canisters"},
    {"id": "book", "name": "Books"},
    {"id": "antique", "name": "Antiques"},
    {"id": "chart", "name": "Star charts"},
)

GOODS_BY_ID: Dict[str, str] = {g["id"]: g["name"] for g in GOODS}
GOOD_IDS: tuple[str, ...] = tuple(g["id"] for g in GOODS)

# Enough copies to deal 4 players (3 market + 3 hand) with cards left to draw.
# Sold cards return under the deck, so the supply recycles.
COPIES_PER_GOOD = 6

STARTING_COINS = 5
HAND_SIZE = 3
MARKET_SIZE = 3
SALE_PRICE = 2
LOOK_COST = 1
CATCH_FINE = 3
ROUND_LIMIT = 8
MIN_PLAYERS = 2
MAX_PLAYERS = 4

# Flavor only. A player picks one; the table never assigns a side.
ROLES: tuple[str, ...] = ("merchant", "smuggler", "pirate", "scavenger")
ROLE_LABELS: Dict[str, str] = {
    "merchant": "Merchant",
    "smuggler": "Smuggler",
    "pirate": "Pirate",
    "scavenger": "Scavenger",
}

SINGLE_POINTS = 2
PAIR_POINTS = 6
TRIPLE_POINTS = 10


@dataclass(frozen=True)
class Card:
    """One good. `id` + `name` are the face; `uid` picks a specific copy."""

    uid: str
    id: str
    name: str

    def face(self) -> dict:
        return {"id": self.id, "name": self.name}


def face_of(card: Card) -> dict:
    return {"uid": card.uid, "id": card.id, "name": card.name}


def points_for_count(n: int) -> int:
    """Best score for n matching goods using single 2, pair 6, three of a kind 10."""
    if n <= 0:
        return 0
    best = [0] * (n + 1)
    for i in range(1, n + 1):
        best[i] = best[i - 1] + SINGLE_POINTS
        if i >= 2:
            best[i] = max(best[i], best[i - 2] + PAIR_POINTS)
        if i >= 3:
            best[i] = max(best[i], best[i - 3] + TRIPLE_POINTS)
    return best[n]


def market_lines(cards: Sequence[Card]) -> List[dict]:
    counts = Counter(c.id for c in cards)
    lines = []
    for good in GOODS:
        n = counts.get(good["id"], 0)
        if n <= 0:
            continue
        lines.append(
            {
                "id": good["id"],
                "name": good["name"],
                "count": n,
                "points": points_for_count(n),
            }
        )
    return lines


def market_points(cards: Sequence[Card]) -> int:
    return sum(line["points"] for line in market_lines(cards))


def create_deck(rng: random.Random) -> List[Card]:
    cards: List[Card] = []
    n = 0
    for good in GOODS:
        for _ in range(COPIES_PER_GOOD):
            n += 1
            cards.append(Card(uid=f"{good['id']}-{n}", id=good["id"], name=good["name"]))
    rng.shuffle(cards)
    return cards


@dataclass
class Offer:
    seller: int
    buyer: int
    card: Card
    claim_id: str
    claim_name: str


@dataclass
class ManifestPlayer:
    name: str
    coins: int = STARTING_COINS
    hand: List[Card] = field(default_factory=list)
    market: List[Card] = field(default_factory=list)
    role: Optional[str] = None

    @property
    def market_points(self) -> int:
        return market_points(self.market)

    @property
    def score(self) -> int:
        return self.coins + self.market_points


class ManifestGame:
    """2–4 players. One sale per turn. Eight rounds, or the table ends early."""

    def __init__(self, player_names: Sequence[str], rng: random.Random | None = None):
        names = [str(n) for n in player_names]
        if not MIN_PLAYERS <= len(names) <= MAX_PLAYERS:
            raise ValueError("MANIFEST needs 2–4 players")
        self.rng = rng or random.Random()
        self.players = [ManifestPlayer(n) for n in names]
        self.deck: List[Card] = create_deck(self.rng)
        self.current = 0
        self.round = 1
        self.turns_played = 0
        self.phase = "selling"  # selling | looking | won
        self.offer: Optional[Offer] = None
        self.last_sale: Optional[dict] = None
        self.winners: List[dict] = []
        self.status = ""
        self._mint_seq = 0
        self._deal()
        self._note_turn()

    def _deal(self) -> None:
        for player in self.players:
            player.coins = STARTING_COINS
            player.market = [self._draw() for _ in range(MARKET_SIZE)]
            player.hand = [self._draw() for _ in range(HAND_SIZE)]

    def _draw(self) -> Card:
        if not self.deck:
            raise RuntimeError("The deck is empty")
        return self.deck.pop()

    def _bury(self, card: Card) -> None:
        """Used cards go back under the deck (the bottom)."""
        self.deck.insert(0, card)

    def _mint_market(self, good_id: str) -> Card:
        """A face-up market good of the settled name. Not the hidden hand card."""
        self._mint_seq += 1
        return Card(uid=f"market-{self._mint_seq}", id=good_id, name=GOODS_BY_ID[good_id])

    def set_role(self, seat: int, role: Optional[str]) -> None:
        if self.phase == "won":
            raise RuntimeError("Match over")
        self._seat(seat)
        if role is None or role == "":
            self.players[seat].role = None
            return
        key = str(role).strip().lower()
        if key not in ROLE_LABELS:
            raise ValueError("Pick merchant, smuggler, pirate, or scavenger")
        self.players[seat].role = key

    def sell(self, seat: int, card_uid: str, claim_id: str, buyer: int) -> None:
        if self.phase == "won":
            raise RuntimeError("Match over")
        if self.phase != "selling":
            raise RuntimeError("Finish the open sale first")
        if seat != self.current:
            raise RuntimeError("Not your turn")
        seller = self._seat(seat)
        if buyer == seat:
            raise RuntimeError("Sell to another player")
        buyer_p = self._seat(buyer)
        claim = str(claim_id or "").strip().lower()
        if claim not in GOODS_BY_ID:
            raise ValueError("Name a good: Helion, plant canisters, books, antiques, or star charts")
        card = next((c for c in seller.hand if c.uid == card_uid), None)
        if card is None:
            raise ValueError("That card is not in your hand")
        if buyer_p.coins < SALE_PRICE:
            raise RuntimeError(f"{buyer_p.name} does not have {SALE_PRICE} coins")

        seller.hand.remove(card)
        buyer_p.coins -= SALE_PRICE
        seller.coins += SALE_PRICE
        self.offer = Offer(
            seller=seat,
            buyer=buyer,
            card=card,
            claim_id=claim,
            claim_name=GOODS_BY_ID[claim],
        )
        self.phase = "looking"
        self.status = (
            f"{seller.name} names {self.offer.claim_name} for {buyer_p.name}. "
            f"{buyer_p.name} paid {SALE_PRICE}. Look for {LOOK_COST}, or let it stand."
        )

    def respond(self, seat: int, look: bool) -> None:
        if self.phase != "looking" or self.offer is None:
            raise RuntimeError("No sale to answer")
        offer = self.offer
        if seat != offer.buyer:
            raise RuntimeError("Only the buyer can look")
        buyer = self.players[seat]
        seller = self.players[offer.seller]
        if look:
            if buyer.coins < LOOK_COST:
                raise RuntimeError("Need 1 coin to look")
            buyer.coins -= LOOK_COST
            seller.coins += LOOK_COST
            if offer.card.id == offer.claim_id:
                self._stand(looked=True)
            else:
                self._caught()
        else:
            self._stand(looked=False)
        self._refill(offer.seller)
        self._advance(offer.seller)

    def end(self, reason: str = "The table ended the game") -> None:
        if self.phase == "won":
            return
        if self.phase == "looking" and self.offer is not None:
            self._unwind_open_sale()
        self._finish(reason)

    def ranking(self) -> List[dict]:
        rows = []
        for i, player in enumerate(self.players):
            lines = market_lines(player.market)
            rows.append(
                {
                    "seat": i,
                    "name": player.name,
                    "role": player.role,
                    "coins": player.coins,
                    "market_points": player.market_points,
                    "score": player.score,
                    "market_lines": lines,
                }
            )
        rows.sort(key=lambda r: (-r["score"], r["seat"]))
        return rows

    def _stand(self, looked: bool) -> None:
        assert self.offer is not None
        offer = self.offer
        # No look: stands as named, even if that name is a lie.
        # Match: the name is the real good, so the market shows that good.
        self.players[offer.buyer].market.append(self._mint_market(offer.claim_id))
        self._bury(offer.card)
        truth = offer.card.face() if looked else None
        if looked:
            text = (
                f"Match. {self.players[offer.buyer].name} keeps {offer.claim_name}."
            )
        else:
            text = (
                f"No look. Sale stands as {offer.claim_name} "
                f"for {self.players[offer.buyer].name}."
            )
        self.last_sale = {
            "seller_seat": offer.seller,
            "buyer_seat": offer.buyer,
            "claim": {"id": offer.claim_id, "name": offer.claim_name},
            "looked": looked,
            "matched": (offer.card.id == offer.claim_id) if looked else None,
            "stood": True,
            "truth": truth,
            "fine_paid": 0,
            "text": text,
        }
        self.offer = None
        self.status = text + f" {self.players[offer.seller].name} draws back to {HAND_SIZE}."

    def _caught(self) -> None:
        """Sale fails. Return the 2, then the seller pays 3 or whatever they have."""
        assert self.offer is not None
        offer = self.offer
        seller = self.players[offer.seller]
        buyer = self.players[offer.buyer]
        refund = min(SALE_PRICE, seller.coins)
        seller.coins -= refund
        buyer.coins += refund
        fine = min(CATCH_FINE, seller.coins)
        seller.coins -= fine
        buyer.coins += fine
        self._bury(offer.card)
        text = (
            f"Caught. It was {offer.card.name}, not {offer.claim_name}. "
            f"Sale fails. {seller.name} pays {buyer.name} {fine}."
        )
        self.last_sale = {
            "seller_seat": offer.seller,
            "buyer_seat": offer.buyer,
            "claim": {"id": offer.claim_id, "name": offer.claim_name},
            "looked": True,
            "matched": False,
            "stood": False,
            "truth": offer.card.face(),
            "fine_paid": fine,
            "text": text,
        }
        self.offer = None
        self.status = text + f" {seller.name} draws back to {HAND_SIZE}."

    def _unwind_open_sale(self) -> None:
        """Table ended before the buyer chose. Give the 2 back and return the card."""
        assert self.offer is not None
        offer = self.offer
        seller = self.players[offer.seller]
        buyer = self.players[offer.buyer]
        refund = min(SALE_PRICE, seller.coins)
        seller.coins -= refund
        buyer.coins += refund
        seller.hand.append(offer.card)
        self.offer = None

    def _refill(self, seat: int) -> None:
        player = self.players[seat]
        while len(player.hand) < HAND_SIZE:
            if not self.deck:
                break
            player.hand.append(self._draw())

    def _advance(self, seller_seat: int) -> None:
        n = len(self.players)
        self.turns_played += 1
        self.current = (seller_seat + 1) % n
        if self.turns_played % n == 0:
            if self.turns_played // n >= ROUND_LIMIT:
                self._finish(f"{ROUND_LIMIT} rounds complete")
                return
            self.round += 1
        sale = self.last_sale["text"] if self.last_sale else ""
        self.phase = "selling"
        self._note_turn()
        if sale:
            self.status = f"{sale} {self.status}"

    def _note_turn(self) -> None:
        seller = self.players[self.current]
        buyers = [
            p.name
            for i, p in enumerate(self.players)
            if i != self.current and p.coins >= SALE_PRICE
        ]
        if not buyers:
            self.status = (
                f"{seller.name} cannot sell — nobody else has {SALE_PRICE} coins. "
                "End the game to score."
            )
            return
        self.status = f"{seller.name}'s turn — sell one card from your hand"

    def _finish(self, reason: str) -> None:
        self.phase = "won"
        self.offer = None
        ranking = self.ranking()
        top = ranking[0]["score"] if ranking else 0
        self.winners = [row for row in ranking if row["score"] == top]
        if len(self.winners) == 1:
            who = self.winners[0]["name"]
            self.status = f"{who} wins with {top}. {reason}."
        else:
            names = " and ".join(row["name"] for row in self.winners)
            self.status = f"{names} tie at {top}. {reason}."

    def _seat(self, seat: int) -> ManifestPlayer:
        if not isinstance(seat, int) or seat < 0 or seat >= len(self.players):
            raise ValueError("Unknown seat")
        return self.players[seat]
