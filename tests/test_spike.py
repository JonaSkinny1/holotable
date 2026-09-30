import random
import unittest

from holotable.spike import (
    SpikeGame,
    SpikeTurnController,
    create_spike_deck,
    hand_total,
    is_bomb,
    stand_points,
    card_value,
)
from holotable.spike_live import SpikeLiveMatch


class TestSpikeDeck(unittest.TestCase):
    def test_composition(self):
        deck = create_spike_deck()
        self.assertEqual(len(deck), 42)
        self.assertEqual(deck.count("NULL"), 2)
        for n in range(1, 11):
            self.assertEqual(deck.count(n), 2)
            self.assertEqual(deck.count(-n), 2)

    def test_values_and_scoring(self):
        self.assertEqual(card_value("NULL"), 0)
        self.assertEqual(card_value(-7), -7)
        self.assertEqual(hand_total([5, -3, "NULL"]), 2)
        self.assertFalse(is_bomb([10, 10, 3]))
        self.assertTrue(is_bomb([10, 10, 4]))
        self.assertEqual(stand_points(["NULL"]), 24)
        self.assertEqual(stand_points([5, -3]), 22)


class TestSpikeGame(unittest.TestCase):
    def test_player_bounds(self):
        with self.assertRaises(ValueError):
            SpikeGame(["Only"])
        with self.assertRaises(ValueError):
            SpikeGame([f"P{i}" for i in range(5)])

    def test_target(self):
        self.assertEqual(SpikeGame.TARGET, 100)

    def test_turn_deal_and_stay(self):
        g = SpikeGame(["A", "B"], rng=random.Random(7))
        tc = SpikeTurnController(game=g)
        early = tc.start()
        self.assertIsNone(early)
        self.assertEqual(len(tc.hand), 2)
        result = tc.stay()
        self.assertFalse(result.busted)
        self.assertEqual(result.points, stand_points(result.hand))

    def test_bomb_on_hit(self):
        g = SpikeGame(["A", "B"], rng=random.Random(0))
        # Force a hand that bombs on next draw
        tc = SpikeTurnController(game=g)
        tc.started = True
        tc.hand = [10, 10, 3]
        # Put a +1 on top of deck
        g.deck.append(1)
        result = tc.hit()
        self.assertIsNotNone(result)
        self.assertTrue(result.busted)
        self.assertEqual(result.points, 0)


class TestSpikeLiveMatch(unittest.TestCase):
    def test_hit_stay_cycle(self):
        m = SpikeLiveMatch(["Pilot", "Engineer"], rng=random.Random(42))
        snap = m.snapshot()
        self.assertEqual(snap["rules"], "spike")
        self.assertEqual(snap["game"], "spike")
        self.assertEqual(snap["title"], "Spike")
        seat = snap["active_seat"]
        # Stay immediately after opening deal
        snap = m.stay(seat)
        self.assertIn(snap["phase"], ("choosing", "won", "between"))
        self.assertEqual(len(snap["players"]), 2)

    def test_wrong_seat(self):
        m = SpikeLiveMatch(["A", "B"], rng=random.Random(1))
        bad = 1 - m.game.current
        with self.assertRaises(RuntimeError):
            m.hit(bad)


if __name__ == "__main__":
    unittest.main()
