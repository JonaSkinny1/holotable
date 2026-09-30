"""Live MANIFEST match on the Holotable Games station.

Same seats, WebSocket, and REST server as the other table games.
Hands stay on the owning datapad. The public table shows markets, coins, and the named sale.
"""

from __future__ import annotations

import random
import threading
from typing import Callable, List, Optional, Set

from .live import DEFAULT_CREW
from .manifest import (
    GOODS,
    ROLE_LABELS,
    ROLES,
    ROUND_LIMIT,
    ManifestGame,
    face_of,
)


class ManifestLiveMatch:
    """Thread-safe MANIFEST match. Sell / look / end / role — not hit / stay."""

    def __init__(
        self,
        player_names: Optional[List[str]] = None,
        rng: random.Random | None = None,
        bot_seats: Optional[Set[int]] = None,
    ):
        names = list(player_names or DEFAULT_CREW[:2])
        if not 2 <= len(names) <= 4:
            names = (names + list(DEFAULT_CREW))[: max(2, min(4, len(names) or 2))]
            if len(names) < 2:
                names = list(DEFAULT_CREW[:2])
        self._lock = threading.RLock()
        self._listeners: List[Callable[[dict], None]] = []
        self.game = ManifestGame(names[:4], rng=rng)
        self.bot_seats: Set[int] = set(bot_seats or ())
        self.match_id = 1

    def on_update(self, cb: Callable[[dict], None]) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(cb)

        def off() -> None:
            with self._lock:
                if cb in self._listeners:
                    self._listeners.remove(cb)

        return off

    def _notify(self) -> None:
        snap = self.snapshot()
        for cb in list(self._listeners):
            try:
                cb(snap)
            except Exception:
                pass

    def new_match(
        self,
        player_names: Optional[List[str]] = None,
        seed: Optional[int] = None,
        bot_seats: Optional[Set[int]] = None,
    ) -> dict:
        with self._lock:
            names = player_names or [p.name for p in self.game.players]
            if not 2 <= len(names) <= 4:
                raise ValueError("MANIFEST needs 2–4 players")
            rng = random.Random(seed) if seed is not None else random.Random()
            self.game = ManifestGame(names, rng=rng)
            if bot_seats is not None:
                self.bot_seats = set(bot_seats)
            self.match_id += 1
            snap = self.snapshot()
        self._notify()
        return snap

    def sell(self, seat: int, card_uid: str, claim_id: str, buyer: int) -> dict:
        with self._lock:
            self.game.sell(int(seat), str(card_uid), str(claim_id), int(buyer))
            snap = self.snapshot_for(int(seat))
        self._notify()
        return snap

    def look(self, seat: int, look: bool) -> dict:
        with self._lock:
            self.game.respond(int(seat), bool(look))
            snap = self.snapshot_for(int(seat))
        self._notify()
        return snap

    def end_match(self, seat: Optional[int] = None) -> dict:
        with self._lock:
            if seat is not None:
                self.game._seat(int(seat))
            self.game.end("The table ended the game")
            viewer = int(seat) if seat is not None else None
            snap = self.snapshot_for(viewer) if viewer is not None else self.snapshot()
        self._notify()
        return snap

    def hit(self, seat: int) -> dict:
        raise RuntimeError("MANIFEST turn is a sale, not a draw")

    def stay(self, seat: int) -> dict:
        raise RuntimeError("MANIFEST turn is a sale, not a bank")

    def set_role(self, seat: int, role: Optional[str]) -> dict:
        with self._lock:
            self.game.set_role(int(seat), role)
            snap = self.snapshot_for(int(seat))
        self._notify()
        return snap

    def bot_act(self, seat: int) -> dict:
        with self._lock:
            if seat not in self.bot_seats:
                raise RuntimeError("Not a computer seat")
            game = self.game
            if game.phase == "selling" and seat == game.current:
                self._bot_sell(seat)
            elif game.phase == "looking" and game.offer is not None and seat == game.offer.buyer:
                self._bot_look(seat)
            else:
                raise RuntimeError("Computer has nothing to do")
            snap = self.snapshot()
        self._notify()
        return snap

    def _bot_sell(self, seat: int) -> None:
        game = self.game
        seller = game.players[seat]
        buyers = [i for i, p in enumerate(game.players) if i != seat and p.coins >= 2]
        if not seller.hand or not buyers:
            raise RuntimeError("Computer cannot sell")
        card = seller.hand[game.rng.randrange(len(seller.hand))]
        if game.rng.random() < 0.45:
            others = [gid for gid in (g["id"] for g in GOODS) if gid != card.id]
            claim = others[game.rng.randrange(len(others))]
        else:
            claim = card.id
        buyer = buyers[game.rng.randrange(len(buyers))]
        game.sell(seat, card.uid, claim, buyer)

    def _bot_look(self, seat: int) -> None:
        game = self.game
        buyer = game.players[seat]
        # Look when the named good would change the market, if they can pay.
        claim = game.offer.claim_id if game.offer else ""
        have = sum(1 for c in buyer.market if c.id == claim)
        want_look = buyer.coins >= 1 and (have in (1, 2) or game.rng.random() < 0.4)
        game.respond(seat, want_look)

    def snapshot(self) -> dict:
        return self.snapshot_for(None)

    def snapshot_for(self, viewer: Optional[int]) -> dict:
        with self._lock:
            return self._snapshot_unlocked(viewer)

    def _snapshot_unlocked(self, viewer: Optional[int]) -> dict:
        g = self.game
        offer = g.offer
        public_offer = None
        if offer is not None:
            public_offer = {
                "seller_seat": offer.seller,
                "seller_name": g.players[offer.seller].name,
                "buyer_seat": offer.buyer,
                "buyer_name": g.players[offer.buyer].name,
                "claim": {"id": offer.claim_id, "name": offer.claim_name},
                "price": 2,
                "look_cost": 1,
            }
        actor = None
        if g.phase == "selling":
            actor = g.current
        elif g.phase == "looking" and offer is not None:
            actor = offer.buyer

        your_hand: List[dict] = []
        offer_truth = None
        if viewer is not None and 0 <= viewer < len(g.players):
            your_hand = [face_of(c) for c in g.players[viewer].hand]
            if offer is not None and viewer == offer.seller:
                offer_truth = face_of(offer.card)

        ranking = g.ranking()
        top = ranking[0]["score"] if ranking else 0
        winner = None
        if g.phase == "won" and len(g.winners) == 1:
            w = g.winners[0]
            winner = {"seat": w["seat"], "name": w["name"], "score": w["score"]}

        return {
            "station": "REACTOR",
            "title": "MANIFEST",
            "rules": "manifest",
            "game": "manifest",
            "match_id": self.match_id,
            "phase": g.phase,
            "round": g.round,
            "round_limit": ROUND_LIMIT,
            "status": g.status,
            "active_seat": g.current,
            "active_name": g.players[g.current].name if g.players else "",
            "active_is_bot": g.current in self.bot_seats,
            "actor_seat": actor,
            "can_act": g.phase in ("selling", "looking"),
            "winner": winner,
            "winners": list(g.winners),
            "tied": g.phase == "won" and len(g.winners) > 1,
            "players": [
                {
                    "seat": i,
                    "name": p.name,
                    "role": p.role,
                    "role_label": ROLE_LABELS.get(p.role or "", ""),
                    "coins": p.coins,
                    "market": [face_of(c) for c in p.market],
                    "market_points": p.market_points,
                    "score": p.score,
                    "market_lines": next(r["market_lines"] for r in ranking if r["seat"] == i),
                    "hand_count": len(p.hand),
                    "active": i == g.current,
                    "is_bot": i in self.bot_seats,
                    "kind": "computer" if i in self.bot_seats else "human",
                    "leading": p.score == top and g.phase == "won",
                }
                for i, p in enumerate(g.players)
            ],
            "scores": ranking,
            "offer": public_offer,
            "offer_truth": offer_truth,
            "your_hand": your_hand,
            "viewer": viewer,
            "last_sale": g.last_sale,
            "goods": [{"id": good["id"], "name": good["name"]} for good in GOODS],
            "roles": [{"id": role, "name": ROLE_LABELS[role]} for role in ROLES],
            "computers": len(self.bot_seats),
            "deck_remaining": len(g.deck),
            "score_legend": "Score = coins + market. One card 2, a pair 6, three of a kind 10.",
            # Public table must not receive a shared hand.
            "hand": [],
            "hand_raw": [],
            "target": None,
        }
