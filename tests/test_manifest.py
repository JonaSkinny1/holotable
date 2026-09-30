"""MANIFEST rules: deal, named sale, look, catch, draw, score."""

from __future__ import annotations

import json
import random
import unittest

from flip7.manifest import (
    CATCH_FINE,
    COPIES_PER_GOOD,
    GOODS,
    HAND_SIZE,
    LOOK_COST,
    MARKET_SIZE,
    ROUND_LIMIT,
    SALE_PRICE,
    STARTING_COINS,
    ManifestGame,
    market_points,
    points_for_count,
)
from flip7.manifest_live import ManifestLiveMatch


def _uids(cards):
    return {c.uid for c in cards}


class TestScoring(unittest.TestCase):
    def test_set_points(self):
        self.assertEqual(points_for_count(0), 0)
        self.assertEqual(points_for_count(1), 2)
        self.assertEqual(points_for_count(2), 6)
        self.assertEqual(points_for_count(3), 10)
        # 4 and 5 still use only single / pair / three of a kind
        self.assertEqual(points_for_count(4), 12)
        self.assertEqual(points_for_count(5), 16)
        self.assertEqual(points_for_count(6), 20)


class TestManifestDealAndSale(unittest.TestCase):
    def setUp(self):
        self.game = ManifestGame(["A", "B"], rng=random.Random(7))

    def test_setup(self):
        self.assertEqual(len(GOODS), 5)
        ids = {g["id"] for g in GOODS}
        self.assertEqual(ids, {"helion", "canister", "book", "antique", "chart"})
        for player in self.game.players:
            self.assertEqual(player.coins, STARTING_COINS)
            self.assertEqual(len(player.market), MARKET_SIZE)
            self.assertEqual(len(player.hand), HAND_SIZE)
            self.assertIsNone(player.role)
            for card in player.market + player.hand:
                self.assertIn(card.id, ids)
                self.assertEqual(set(card.face()), {"id", "name"})
        dealt = 2 * (MARKET_SIZE + HAND_SIZE)
        self.assertEqual(len(self.game.deck), len(GOODS) * COPIES_PER_GOOD - dealt)
        self.assertEqual(self.game.phase, "selling")
        self.assertEqual(self.game.round, 1)

    def test_rejects_bad_table_size(self):
        with self.assertRaises(ValueError):
            ManifestGame(["solo"])
        with self.assertRaises(ValueError):
            ManifestGame(["a", "b", "c", "d", "e"])

    def test_no_look_stands_as_named(self):
        seller = self.game.players[0]
        buyer = self.game.players[1]
        card = seller.hand[0]
        claim = next(g["id"] for g in GOODS if g["id"] != card.id)
        before_claim = sum(1 for c in buyer.market if c.id == claim)
        before_truth = sum(1 for c in buyer.market if c.id == card.id)
        coins = (seller.coins, buyer.coins)
        self.game.sell(0, card.uid, claim, 1)
        self.assertEqual(self.game.phase, "looking")
        self.assertEqual(seller.coins, coins[0] + SALE_PRICE)
        self.assertEqual(buyer.coins, coins[1] - SALE_PRICE)
        self.assertNotIn(card.uid, _uids(seller.hand))
        self.game.respond(1, look=False)
        self.assertEqual(sum(1 for c in buyer.market if c.id == claim), before_claim + 1)
        self.assertEqual(sum(1 for c in buyer.market if c.id == card.id), before_truth)
        self.assertNotIn(card.uid, _uids(buyer.market))
        self.assertEqual(self.game.deck[0].uid, card.uid)
        self.assertEqual(len(seller.hand), HAND_SIZE)
        self.assertEqual(self.game.last_sale["stood"], True)
        self.assertIsNone(self.game.last_sale["truth"])
        self.assertEqual(self.game.current, 1)
        self.assertEqual(seller.coins + buyer.coins, STARTING_COINS * 2)

    def test_look_match_stands(self):
        seller = self.game.players[0]
        buyer = self.game.players[1]
        card = seller.hand[0]
        before = sum(1 for c in buyer.market if c.id == card.id)
        self.game.sell(0, card.uid, card.id, 1)
        self.game.respond(1, look=True)
        self.assertEqual(sum(1 for c in buyer.market if c.id == card.id), before + 1)
        self.assertEqual(seller.coins, STARTING_COINS + SALE_PRICE + LOOK_COST)
        self.assertEqual(buyer.coins, STARTING_COINS - SALE_PRICE - LOOK_COST)
        self.assertEqual(self.game.last_sale["matched"], True)
        self.assertEqual(self.game.last_sale["truth"]["id"], card.id)
        self.assertEqual(len(seller.hand), HAND_SIZE)
        self.assertEqual(self.game.deck[0].uid, card.uid)

    def test_look_miss_fails_and_fines(self):
        seller = self.game.players[0]
        buyer = self.game.players[1]
        card = seller.hand[0]
        claim = next(g["id"] for g in GOODS if g["id"] != card.id)
        market_before = [c.uid for c in buyer.market]
        self.game.sell(0, card.uid, claim, 1)
        self.game.respond(1, look=True)
        self.assertEqual([c.uid for c in buyer.market], market_before)
        # Paid 2, paid 1 to look, got 2 back, got 3. Net +2.
        self.assertEqual(buyer.coins, STARTING_COINS + (CATCH_FINE - LOOK_COST))
        self.assertEqual(seller.coins, STARTING_COINS - (CATCH_FINE - LOOK_COST))
        self.assertEqual(self.game.last_sale["stood"], False)
        self.assertEqual(self.game.last_sale["fine_paid"], CATCH_FINE)
        self.assertEqual(self.game.last_sale["truth"]["id"], card.id)
        self.assertEqual(self.game.last_sale["truth"]["name"], card.name)
        self.assertEqual(len(seller.hand), HAND_SIZE)
        self.assertEqual(self.game.deck[0].uid, card.uid)
        self.assertEqual(seller.coins + buyer.coins, STARTING_COINS * 2)

    def test_fine_is_whatever_the_seller_has(self):
        seller = self.game.players[0]
        buyer = self.game.players[1]
        seller.coins = 0
        buyer.coins = 5
        card = seller.hand[0]
        claim = next(g["id"] for g in GOODS if g["id"] != card.id)
        self.game.sell(0, card.uid, claim, 1)
        self.game.respond(1, look=True)
        # Seller held 0, received 2 + 1, refunded 2, had 1 left, pays that 1.
        self.assertEqual(self.game.last_sale["fine_paid"], 1)
        self.assertEqual(seller.coins, 0)
        self.assertEqual(buyer.coins, 5)
        self.assertLess(self.game.last_sale["fine_paid"], CATCH_FINE)

    def test_buyer_needs_two_coins(self):
        self.game.players[1].coins = 1
        card = self.game.players[0].hand[0]
        with self.assertRaises(RuntimeError):
            self.game.sell(0, card.uid, card.id, 1)
        self.assertEqual(self.game.phase, "selling")
        self.assertEqual(len(self.game.players[0].hand), HAND_SIZE)

    def test_cannot_sell_to_self_or_out_of_turn(self):
        card = self.game.players[0].hand[0]
        with self.assertRaises(RuntimeError):
            self.game.sell(0, card.uid, card.id, 0)
        with self.assertRaises(RuntimeError):
            self.game.sell(1, self.game.players[1].hand[0].uid, card.id, 0)

    def test_role_is_chosen_not_assigned(self):
        self.assertIsNone(self.game.players[0].role)
        self.game.set_role(0, "Pirate")
        self.assertEqual(self.game.players[0].role, "pirate")
        self.game.set_role(1, "")
        self.assertIsNone(self.game.players[1].role)
        with self.assertRaises(ValueError):
            self.game.set_role(0, "pilot")

    def test_score_is_coins_plus_market(self):
        self.game.end("stop")
        for player in self.game.players:
            self.assertEqual(player.score, player.coins + market_points(player.market))
        self.assertEqual(self.game.phase, "won")
        self.assertTrue(self.game.winners)
        self.assertIn("stop", self.game.status)

    def test_end_during_offer_returns_the_coins(self):
        seller = self.game.players[0]
        buyer = self.game.players[1]
        card = seller.hand[0]
        self.game.sell(0, card.uid, card.id, 1)
        self.game.end("agreed")
        self.assertEqual(seller.coins, STARTING_COINS)
        self.assertEqual(buyer.coins, STARTING_COINS)
        self.assertIn(card.uid, _uids(seller.hand))
        self.assertEqual(self.game.phase, "won")

    def test_eight_rounds_ends(self):
        guard = 0
        while self.game.phase != "won":
            guard += 1
            self.assertLess(guard, 40)
            seat = self.game.current
            card = self.game.players[seat].hand[0]
            buyer = (seat + 1) % 2
            self.game.sell(seat, card.uid, card.id, buyer)
            self.game.respond(buyer, look=False)
        self.assertEqual(self.game.turns_played, ROUND_LIMIT * 2)
        self.assertIn("8 rounds", self.game.status)
        for player in self.game.players:
            self.assertEqual(player.score, player.coins + player.market_points)


class TestManifestPrivacy(unittest.TestCase):
    def test_public_snapshot_hides_hands(self):
        match = ManifestLiveMatch(["A", "B"], rng=random.Random(3))
        public = match.snapshot()
        blob = json.dumps(public)
        self.assertEqual(public["rules"], "manifest")
        self.assertEqual(public["your_hand"], [])
        self.assertIsNone(public["offer_truth"])
        for seat, player in enumerate(match.game.players):
            for card in player.hand:
                self.assertNotIn(card.uid, blob)
            private = match.snapshot_for(seat)
            seen = {c["uid"] for c in private["your_hand"]}
            self.assertEqual(seen, _uids(player.hand))
            other = 1 - seat
            other_uids = _uids(match.game.players[other].hand)
            self.assertTrue(seen.isdisjoint(other_uids))

    def test_seller_sees_truth_buyer_does_not_until_look(self):
        match = ManifestLiveMatch(["A", "B"], rng=random.Random(4))
        card = match.game.players[0].hand[0]
        claim = next(g["id"] for g in GOODS if g["id"] != card.id)
        match.game.sell(0, card.uid, claim, 1)
        seller_view = match.snapshot_for(0)
        buyer_view = match.snapshot_for(1)
        public = match.snapshot()
        self.assertEqual(seller_view["offer_truth"]["id"], card.id)
        self.assertIsNone(buyer_view["offer_truth"])
        self.assertIsNone(public["offer_truth"])
        self.assertNotIn(card.uid, json.dumps(public))
        self.assertEqual(public["offer"]["claim"]["id"], claim)
        match.game.respond(1, look=True)
        shown = match.snapshot()
        self.assertEqual(shown["last_sale"]["truth"]["id"], card.id)
        self.assertFalse(shown["last_sale"]["stood"])

    def test_bot_can_answer_a_sale(self):
        match = ManifestLiveMatch(["Pilot", "COSMOS"], rng=random.Random(5), bot_seats={1})
        card = match.game.players[0].hand[0]
        match.sell(0, card.uid, card.id, 1)
        self.assertEqual(match.game.phase, "looking")
        match.bot_act(1)
        self.assertEqual(match.game.phase, "selling")
        self.assertEqual(match.game.current, 1)
        self.assertEqual(len(match.game.players[0].hand), HAND_SIZE)
        match.bot_act(1)
        self.assertEqual(match.game.phase, "looking")
        self.assertEqual(match.game.offer.buyer, 0)
