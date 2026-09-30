"""MANIFEST on the existing Holotable server: deal, sell, look, catch, score."""

from __future__ import annotations

import json
import random
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib import error, request

from flip7.live import LiveMatch
from flip7.manifest import GOODS
from flip7.server import HeliosHandler, get_game_id, set_match


class TestManifestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        set_match(LiveMatch(["Pilot", "Engineer"], rng=random.Random(2)), game_id="flip7")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), HeliosHandler)
        cls.httpd.daemon_threads = True
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _get(self, path):
        with request.urlopen(self.base + path, timeout=3) as resp:
            return resp.status, json.loads(resp.read().decode())

    def _post(self, path, body=None):
        data = json.dumps(body or {}).encode()
        req = request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=3) as resp:
                return resp.status, json.loads(resp.read().decode())
        except error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_two_player_sale_look_catch_and_score(self):
        code, state = self._post(
            "/api/game",
            {"game": "manifest", "players": ["A", "B"], "seed": 11, "seat": 0},
        )
        self.assertEqual(code, 200)
        self.assertEqual(state.get("rules"), "manifest")
        self.assertEqual(state.get("title"), "MANIFEST")
        self.assertEqual(get_game_id(), "manifest")
        self.assertEqual(len(state["your_hand"]), 3)
        self.assertEqual(len(state["players"]), 2)
        for player in state["players"]:
            self.assertEqual(player["coins"], 5)
            self.assertEqual(len(player["market"]), 3)
            self.assertEqual(player["hand_count"], 3)
            self.assertIsNone(player["role"])
        public_ids = {g["id"] for g in state["goods"]}
        self.assertEqual(public_ids, {g["id"] for g in GOODS})

        _, public = self._get("/api/state")
        self.assertEqual(public["your_hand"], [])
        hand_uids = {c["uid"] for c in state["your_hand"]}
        self.assertTrue(hand_uids.isdisjoint(_public_uids(public)))

        card = state["your_hand"][0]
        claim = next(g["id"] for g in state["goods"] if g["id"] != card["id"])
        code, offered = self._post(
            "/api/sell",
            {"seat": 0, "card": card["uid"], "claim": claim, "buyer": 1},
        )
        self.assertEqual(code, 200, offered)
        self.assertEqual(offered["phase"], "looking")
        self.assertEqual(offered["offer"]["claim"]["id"], claim)
        self.assertEqual(offered["offer_truth"]["id"], card["id"])
        self.assertEqual(offered["players"][1]["coins"], 3)
        self.assertEqual(offered["players"][0]["coins"], 7)

        _, buyer = self._get("/api/state?seat=1")
        self.assertIsNone(buyer["offer_truth"])
        self.assertEqual(len(buyer["your_hand"]), 3)
        self.assertTrue(hand_uids.isdisjoint({c["uid"] for c in buyer["your_hand"]}))

        code, caught = self._post("/api/look", {"seat": 1, "look": True})
        self.assertEqual(code, 200, caught)
        self.assertEqual(caught["phase"], "selling")
        self.assertFalse(caught["last_sale"]["stood"])
        self.assertEqual(caught["last_sale"]["truth"]["id"], card["id"])
        self.assertEqual(caught["last_sale"]["fine_paid"], 3)
        self.assertEqual(caught["players"][0]["hand_count"], 3)
        self.assertEqual(caught["active_seat"], 1)
        self.assertEqual(caught["players"][0]["coins"] + caught["players"][1]["coins"], 10)

        # Seat 1 sells the truth and seat 0 lets it stand.
        _, seat1 = self._get("/api/state?seat=1")
        real = seat1["your_hand"][0]
        code, named = self._post(
            "/api/sell",
            {"seat": 1, "card": real["uid"], "claim": real["id"], "buyer": 0},
        )
        self.assertEqual(code, 200, named)
        before = sum(1 for c in named["players"][0]["market"] if c["id"] == real["id"])
        code, stood = self._post("/api/look", {"seat": 0, "look": False})
        self.assertEqual(code, 200, stood)
        self.assertTrue(stood["last_sale"]["stood"])
        self.assertIsNone(stood["last_sale"]["truth"])
        after = sum(1 for c in stood["players"][0]["market"] if c["id"] == real["id"])
        self.assertEqual(after, before + 1)
        self.assertEqual(stood["players"][1]["hand_count"], 3)

        code, role = self._post("/api/role", {"seat": 0, "role": "scavenger"})
        self.assertEqual(code, 200, role)
        self.assertEqual(role["players"][0]["role"], "scavenger")
        self.assertEqual(role["players"][1]["role"], None)

        code, ended = self._post("/api/end", {"seat": 0})
        self.assertEqual(code, 200, ended)
        self.assertEqual(ended["phase"], "won")
        self.assertTrue(ended["scores"])
        for row in ended["scores"]:
            self.assertEqual(row["score"], row["coins"] + row["market_points"])
        self.assertIn("ended", ended["status"].lower())
        top = ended["scores"][0]["score"]
        self.assertTrue(any(row["score"] == top for row in ended["winners"]))

        code, health = self._get("/api/health")
        self.assertIn("manifest", health["games"])
        code, games = self._get("/api/games")
        ids = [g["id"] for g in games["games"]]
        self.assertIn("manifest", ids)
        self.assertEqual(games["games"][ids.index("manifest")]["title"], "MANIFEST")

        with request.urlopen(self.base + "/", timeout=3) as resp:
            body = resp.read().decode()
        self.assertIn("MANIFEST", body)
        self.assertIn("data-game=\"manifest\"", body)
        self.assertIn("score-card", body)
        self.assertIn(">Games</button>", body)
        self.assertNotIn("pick-manifest", body)

        with request.urlopen(self.base + "/pad.html", timeout=3) as resp:
            pad = resp.read().decode()
        self.assertIn("btn-sell", pad)
        self.assertIn("btn-look", pad)
        self.assertIn("MANIFEST", pad)


def _public_uids(state):
    found = set()
    for player in state.get("players") or []:
        for card in player.get("market") or []:
            if card.get("uid"):
                found.add(card["uid"])
    return found


if __name__ == "__main__":
    unittest.main()
