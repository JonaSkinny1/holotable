"""Holotable server — static UI + REST + WebSocket broadcast.

Software only (no actuators / MQTT). Serves the five-station Holotable.
The Games station runs Flip 7, Stake, or MANIFEST from one menu.
Computer opponents auto-act server-side (no datapad required).
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from .bots import BOT_NAMES, build_roster, decide_from_snapshot
from .live import DEFAULT_CREW, LiveMatch
from .manifest_live import ManifestLiveMatch
from .stake_live import StakeLiveMatch
from . import wsutil

STATIC_DIR = Path(__file__).resolve().parent / "web"

MatchType = Union[LiveMatch, StakeLiveMatch, ManifestLiveMatch]

_state_lock = threading.Lock()
_game_id = "flip7"
_computers = 0
_match: MatchType = LiveMatch(DEFAULT_CREW[:2])
_clients: Set["WsClient"] = set()
_clients_lock = threading.Lock()
_bot_timer: Optional[threading.Timer] = None
_bot_timer_lock = threading.Lock()


def _env_num(name: str, legacy: str, default: str) -> float:
    """Read HOLOTABLE_* first. HELIOS_* remains so older shells still work."""
    raw = os.environ.get(name, os.environ.get(legacy, default))
    return float(raw)


_bot_delay_sec = _env_num("HOLOTABLE_BOT_DELAY", "HELIOS_BOT_DELAY", "0.75")


def get_match() -> MatchType:
    with _state_lock:
        return _match


def get_game_id() -> str:
    with _state_lock:
        return _game_id


def get_computers() -> int:
    with _state_lock:
        return _computers


def set_match(m: MatchType, game_id: Optional[str] = None, computers: Optional[int] = None) -> None:
    global _match, _game_id, _computers
    with _state_lock:
        _match = m
        if game_id is not None:
            _game_id = game_id
        elif isinstance(m, StakeLiveMatch):
            _game_id = "stake"
        elif isinstance(m, ManifestLiveMatch):
            _game_id = "manifest"
        else:
            _game_id = "flip7"
        if computers is not None:
            _computers = int(computers)
        else:
            _computers = len(getattr(m, "bot_seats", ()) or ())
    m.on_update(_on_match_update)
    _on_match_update(m.snapshot())


def _parse_computers(body: dict, default: Optional[int] = None) -> Optional[int]:
    if "computers" in body:
        return int(body["computers"])
    if "bots" in body:
        return int(body["bots"])
    if "computer_opponents" in body:
        return int(body["computer_opponents"])
    return default


def _human_names_from_body(body: dict) -> Optional[List[str]]:
    names = body.get("players") or body.get("names") or body.get("human_names")
    if names is None:
        return None
    if isinstance(names, str):
        return [names]
    return list(names)


def _roster_for(
    game: str,
    computers: int,
    human_names: Optional[List[str]] = None,
) -> tuple:
    return build_roster(computers=computers, human_names=human_names, game=game)


def normalize_game(game: str) -> str:
    g = (game or "").strip().lower()
    if g in ("flip7", "reactor", "reactor_overload", "flip"):
        return "flip7"
    if g == "stake":
        return "stake"
    if g == "manifest":
        return "manifest"
    raise ValueError("Unknown game — use flip7, stake, or manifest")


def _make_match(game: str, names: List[str], rng, bot_seats: Set[int]) -> MatchType:
    if game == "stake":
        return StakeLiveMatch(names, rng=rng, bot_seats=bot_seats)
    if game == "manifest":
        return ManifestLiveMatch(names, rng=rng, bot_seats=bot_seats)
    return LiveMatch(names, rng=rng, bot_seats=bot_seats)


def _clamp_names(game: str, names: List[str]) -> List[str]:
    if game == "flip7":
        if not (2 <= len(names) <= 6):
            return list(DEFAULT_CREW[: max(2, min(4, len(names) or 2))])
        return names
    # Stake and MANIFEST: 2–4 seats
    if len(names) > 4:
        names = names[:4]
    if len(names) < 2:
        names = list(DEFAULT_CREW[:2])
    return names


def switch_game(
    game: str,
    player_names: Optional[List[str]] = None,
    seed: Optional[int] = None,
    computers: Optional[int] = None,
) -> dict:
    """Start a new Flip 7, Stake, or MANIFEST match on the Holotable."""
    g = normalize_game(game)

    n_comp = get_computers() if computers is None else max(0, min(3, int(computers)))

    import random

    rng = random.Random(seed) if seed is not None else random.Random()

    # Explicit players list without a computers key → all-human (API compat).
    # When computers is set/preserved, rebuild Pilot + bot roster.
    if player_names is not None and computers is None:
        names = _clamp_names(g, list(player_names))
        bot_seats = set()
        m = _make_match(g, names, rng, bot_seats)
        set_match(m, game_id=g, computers=0)
        return m.snapshot()

    humans = player_names
    if humans is not None:
        bot_set = set(BOT_NAMES)
        filtered = [n for n in humans if n not in bot_set]
        humans = filtered or ["Pilot"]

    names, bot_seats = _roster_for(g, n_comp, humans)
    m = _make_match(g, names, rng, bot_seats)
    set_match(m, game_id=g, computers=n_comp)
    return m.snapshot()


def apply_computers(
    computers: int,
    human_names: Optional[List[str]] = None,
    seed: Optional[int] = None,
    game: Optional[str] = None,
) -> dict:
    """Rebuild current (or specified) game with N computer opponents."""
    g = game or get_game_id()
    n = max(0, min(3, int(computers)))
    return switch_game(g, player_names=human_names, seed=seed, computers=n)


def new_match_with_options(
    match: MatchType,
    names: Optional[List[str]],
    seed: Optional[int],
    computers: Optional[int],
) -> dict:
    if computers is not None:
        return apply_computers(computers, human_names=names, seed=seed)
    if names is not None:
        # Preserve existing bot seats if names length matches and bots present
        bot_seats = set(getattr(match, "bot_seats", ()) or ())
        snap = match.new_match(player_names=names, seed=seed, bot_seats=bot_seats)
        return snap
    return match.new_match(seed=seed)


class WsClient:
    def __init__(self, sock, role: str, seat: Optional[int]):
        self.sock = sock
        self.role = role
        self.seat = seat
        self.lock = threading.Lock()

    def send_json(self, obj: dict) -> None:
        data = wsutil.encode_text(json.dumps(obj, default=str))
        with self.lock:
            self.sock.sendall(data)


def _view_for(client: WsClient, state: dict) -> dict:
    """Pads get that seat's private hand. The table gets the public snapshot."""
    match = get_match()
    if client.role == "pad" and client.seat is not None and hasattr(match, "snapshot_for"):
        try:
            return match.snapshot_for(client.seat)
        except Exception:
            return state
    return state


def broadcast(state: dict) -> None:
    dead: List[WsClient] = []
    with _clients_lock:
        clients = list(_clients)
    for c in clients:
        try:
            c.send_json({"type": "state", "state": _view_for(c, state)})
        except Exception:
            dead.append(c)
    if dead:
        with _clients_lock:
            for c in dead:
                _clients.discard(c)


def _cancel_bot_timer() -> None:
    global _bot_timer
    with _bot_timer_lock:
        if _bot_timer is not None:
            try:
                _bot_timer.cancel()
            except Exception:
                pass
            _bot_timer = None


def _bot_seat_to_act(state: dict) -> Optional[int]:
    """Seat a computer must act on, or None. MANIFEST looks are the buyer's decision."""
    if not state or state.get("phase") == "won" or state.get("winner"):
        return None
    rules = state.get("rules") or state.get("game")
    players = state.get("players") or []
    if rules == "manifest":
        if state.get("phase") == "selling":
            seat = state.get("active_seat")
            if not any(p.get("seat") != seat and int(p.get("coins") or 0) >= 2 for p in players):
                return None
        elif state.get("phase") == "looking":
            seat = (state.get("offer") or {}).get("buyer_seat")
        else:
            return None
    else:
        if state.get("phase") != "choosing" or not state.get("can_act"):
            return None
        seat = state.get("active_seat")
    if seat is None or not isinstance(seat, int) or seat < 0 or seat >= len(players):
        return None
    if not players[seat].get("is_bot"):
        return None
    return seat


def _run_bot_turn(expected_match_id: int, expected_seat: int) -> None:
    match = get_match()
    try:
        state = match.snapshot()
    except Exception:
        return
    if state.get("match_id") != expected_match_id:
        return
    if _bot_seat_to_act(state) != expected_seat:
        return
    if (state.get("rules") or state.get("game")) == "manifest":
        try:
            match.bot_act(expected_seat)  # type: ignore[attr-defined]
        except (RuntimeError, ValueError, TypeError):
            pass
        return
    decision = decide_from_snapshot(state)
    if decision is None:
        return
    try:
        if decision == "hit":
            match.hit(expected_seat)
        else:
            match.stay(expected_seat)
    except (RuntimeError, ValueError, TypeError):
        pass


def _schedule_bot_if_needed(state: dict) -> None:
    _cancel_bot_timer()
    seat = _bot_seat_to_act(state)
    if seat is None:
        return
    mid = state.get("match_id")
    try:
        delay = _env_num("HOLOTABLE_BOT_DELAY", "HELIOS_BOT_DELAY", str(_bot_delay_sec))
    except ValueError:
        delay = _bot_delay_sec
    timer = threading.Timer(delay, _run_bot_turn, args=(mid, seat))
    timer.daemon = True
    with _bot_timer_lock:
        global _bot_timer
        _bot_timer = timer
        timer.start()


def _on_match_update(state: dict) -> None:
    broadcast(state)
    _schedule_bot_if_needed(state)


_match.on_update(_on_match_update)


def _seat_from_body(body: dict) -> Optional[int]:
    if "seat" not in body or body.get("seat") is None or body.get("seat") == "":
        return None
    return int(body["seat"])


def _private_view(snap: dict, body: dict) -> dict:
    """REST replies to a datapad include that seat's hand."""
    seat = _seat_from_body(body)
    match = get_match()
    if seat is None or not hasattr(match, "snapshot_for"):
        return snap
    try:
        return match.snapshot_for(seat)
    except (RuntimeError, ValueError, TypeError):
        return snap


def _state_for_query(qs: Dict[str, List[str]]) -> dict:
    match = get_match()
    raw = (qs.get("seat") or [None])[0]
    if raw is None or not str(raw).lstrip("-").isdigit() or not hasattr(match, "snapshot_for"):
        return match.snapshot()
    try:
        return match.snapshot_for(int(raw))
    except (RuntimeError, ValueError, TypeError):
        return match.snapshot()


def json_bytes(obj: Any, code: int = 200) -> tuple[int, bytes, str]:
    body = json.dumps(obj, default=str).encode("utf-8")
    return code, body, "application/json; charset=utf-8"


class HolotableHandler(BaseHTTPRequestHandler):
    server_version = "Holotable/0.5"

    def log_message(self, fmt: str, *args) -> None:
        if os.environ.get("HOLOTABLE_VERBOSE") or os.environ.get("HELIOS_VERBOSE"):
            super().log_message(fmt, *args)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/ws":
            self._websocket(qs)
            return
        # /api/reactor/* stays as a legacy alias. The station label is Games.
        if path in ("/api/state", "/api/reactor/state"):
            self._send(*json_bytes(_state_for_query(qs)))
            return
        if path == "/api/health":
            self._send(
                *json_bytes(
                    {
                        "ok": True,
                        "app": "Holotable",
                        "shell": "HOLOTABLE",
                        "outpost": "Ohio Outpost // Sol-3",
                        "games": ["flip7", "stake", "manifest"],
                        "active_game": get_game_id(),
                        "computers": get_computers(),
                        "bot_names": list(BOT_NAMES[:3]),
                    }
                )
            )
            return
        if path == "/api/games":
            self._send(
                *json_bytes(
                    {
                        "games": [
                            {"id": "flip7", "title": "Flip 7"},
                            {"id": "stake", "title": "Stake"},
                            {"id": "manifest", "title": "MANIFEST"},
                        ],
                        "active": get_game_id(),
                        "computers": get_computers(),
                    }
                )
            )
            return

        self._static(path)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send(*json_bytes({"error": "invalid JSON"}, 400))
            return

        match = get_match()
        try:
            if path in ("/api/computers", "/api/reactor/computers", "/api/bots"):
                n = _parse_computers(body)
                if n is None:
                    raise ValueError("Need computers (0–3)")
                humans = _human_names_from_body(body)
                snap = apply_computers(n, human_names=humans, seed=body.get("seed"), game=body.get("game"))
                self._send(*json_bytes(_private_view(snap, body)))
                return
            if path in ("/api/game", "/api/reactor/game"):
                names = _human_names_from_body(body)
                seed = body.get("seed")
                game = body.get("game") or body.get("rules") or body.get("id")
                computers = _parse_computers(body)
                snap = switch_game(str(game), player_names=names, seed=seed, computers=computers)
                self._send(*json_bytes(_private_view(snap, body)))
                return
            if path in ("/api/new", "/api/reactor/new"):
                names = _human_names_from_body(body)
                seed = body.get("seed")
                computers = _parse_computers(body)
                if body.get("game") or body.get("rules"):
                    snap = switch_game(
                        str(body.get("game") or body.get("rules")),
                        player_names=names,
                        seed=seed,
                        computers=computers if computers is not None else get_computers(),
                    )
                    self._send(*json_bytes(_private_view(snap, body)))
                    return
                snap = new_match_with_options(match, names, seed, computers)
                self._send(*json_bytes(_private_view(snap, body)))
                return
            if path in ("/api/hit", "/api/reactor/hit"):
                seat = int(body.get("seat", 0))
                snap = match.hit(seat)
                self._send(*json_bytes(_private_view(snap, body)))
                return
            if path in ("/api/stay", "/api/reactor/stay"):
                seat = int(body.get("seat", 0))
                snap = match.stay(seat)
                self._send(*json_bytes(_private_view(snap, body)))
                return
            if path in ("/api/sell", "/api/manifest/sell"):
                seat = int(body.get("seat", 0))
                buyer = body.get("buyer", body.get("buyer_seat"))
                card = body.get("card", body.get("card_uid"))
                claim = body.get("claim", body.get("claim_id"))
                snap = match.sell(seat, card, claim, int(buyer))  # type: ignore[attr-defined]
                self._send(*json_bytes(_private_view(snap, body)))
                return
            if path in ("/api/look", "/api/manifest/look"):
                seat = int(body.get("seat", 0))
                look = body.get("look", body.get("inspect"))
                if isinstance(look, str):
                    look = look.strip().lower() in ("1", "true", "yes", "look")
                snap = match.look(seat, bool(look))  # type: ignore[attr-defined]
                self._send(*json_bytes(_private_view(snap, body)))
                return
            if path in ("/api/end", "/api/manifest/end"):
                raw_seat = body.get("seat")
                seat = int(raw_seat) if raw_seat is not None and raw_seat != "" else None
                snap = match.end_match(seat)  # type: ignore[attr-defined]
                self._send(*json_bytes(_private_view(snap, body)))
                return
            if path in ("/api/role", "/api/manifest/role"):
                seat = int(body.get("seat", 0))
                snap = match.set_role(seat, body.get("role"))  # type: ignore[attr-defined]
                self._send(*json_bytes(_private_view(snap, body)))
                return
        except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
            self._send(*json_bytes({"error": str(exc)}, 400))
            return

        self._send(*json_bytes({"error": "not found"}, 404))

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        rel = path.lstrip("/")
        if ".." in rel.split("/"):
            self._send(*json_bytes({"error": "bad path"}, 400))
            return
        file_path = (STATIC_DIR / rel).resolve()
        if not str(file_path).startswith(str(STATIC_DIR.resolve())):
            self._send(*json_bytes({"error": "bad path"}, 400))
            return
        if not file_path.is_file():
            self.send_response(404)
            self._cors()
            self.end_headers()
            self.wfile.write(b"not found")
            return
        ctype, _ = mimetypes.guess_type(str(file_path))
        data = file_path.read_bytes()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _websocket(self, qs: Dict[str, List[str]]) -> None:
        key = self.headers.get("Sec-WebSocket-Key")
        if not key or self.headers.get("Upgrade", "").lower() != "websocket":
            self._send(*json_bytes({"error": "expected websocket"}, 400))
            return
        role = (qs.get("role") or ["table"])[0]
        seat_raw = (qs.get("seat") or [None])[0]
        seat = int(seat_raw) if seat_raw is not None and str(seat_raw).isdigit() else None
        _handle_ws(self, key, role, seat)


def _handle_ws(handler: HolotableHandler, key: str, role: str, seat: Optional[int]) -> None:
    sock = handler.request
    sock.sendall(wsutil.handshake_response(key))
    client = WsClient(sock, role, seat)
    with _clients_lock:
        _clients.add(client)
    try:
        client.send_json({"type": "hello", "role": role, "seat": seat})
        client.send_json({"type": "state", "state": _view_for(client, get_match().snapshot())})
        while True:
            opcode, data = wsutil.read_frame(sock.recv)
            if opcode == 0x8:
                break
            if opcode == 0x9:
                sock.sendall(wsutil.encode_pong(data))
                continue
            if opcode != 0x1:
                continue
            try:
                msg = json.loads(data.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            _dispatch_ws(client, msg)
    except Exception:
        pass
    finally:
        with _clients_lock:
            _clients.discard(client)
        try:
            sock.close()
        except Exception:
            pass


def _dispatch_ws(client: WsClient, msg: dict) -> None:
    mtype = msg.get("type")
    match = get_match()
    try:
        if mtype == "hit":
            seat = int(msg.get("seat", client.seat if client.seat is not None else 0))
            match.hit(seat)
        elif mtype == "stay":
            seat = int(msg.get("seat", client.seat if client.seat is not None else 0))
            match.stay(seat)
        elif mtype == "sell":
            seat = int(msg.get("seat", client.seat if client.seat is not None else 0))
            buyer = msg.get("buyer", msg.get("buyer_seat"))
            card = msg.get("card", msg.get("card_uid"))
            claim = msg.get("claim", msg.get("claim_id"))
            match.sell(seat, card, claim, int(buyer))  # type: ignore[attr-defined]
        elif mtype == "look":
            seat = int(msg.get("seat", client.seat if client.seat is not None else 0))
            look = msg.get("look", msg.get("inspect"))
            if isinstance(look, str):
                look = look.strip().lower() in ("1", "true", "yes", "look")
            match.look(seat, bool(look))  # type: ignore[attr-defined]
        elif mtype == "end":
            raw_seat = msg.get("seat", client.seat)
            seat = int(raw_seat) if raw_seat is not None and raw_seat != "" else None
            match.end_match(seat)  # type: ignore[attr-defined]
        elif mtype == "set_role":
            seat = int(msg.get("seat", client.seat if client.seat is not None else 0))
            match.set_role(seat, msg.get("role"))  # type: ignore[attr-defined]
        elif mtype == "new":
            computers = _parse_computers(msg)
            if msg.get("game") or msg.get("rules"):
                switch_game(
                    str(msg.get("game") or msg.get("rules")),
                    player_names=msg.get("players") or msg.get("human_names"),
                    seed=msg.get("seed"),
                    computers=computers if computers is not None else get_computers(),
                )
            else:
                new_match_with_options(
                    match,
                    msg.get("players") or msg.get("human_names"),
                    msg.get("seed"),
                    computers,
                )
        elif mtype == "set_game":
            switch_game(
                str(msg.get("game") or msg.get("rules") or ""),
                player_names=msg.get("players") or msg.get("human_names"),
                seed=msg.get("seed"),
                computers=_parse_computers(msg),
            )
        elif mtype in ("set_computers", "computers", "bots"):
            n = _parse_computers(msg)
            if n is None:
                raise ValueError("Need computers (0–3)")
            apply_computers(
                n,
                human_names=msg.get("players") or msg.get("human_names"),
                seed=msg.get("seed"),
                game=msg.get("game"),
            )
        elif mtype == "ping":
            client.send_json({"type": "pong"})
        elif mtype == "get_state":
            client.send_json({"type": "state", "state": _view_for(client, match.snapshot())})
    except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
        try:
            client.send_json({"type": "error", "error": str(exc)})
        except Exception:
            pass


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Holotable — Flip 7 / Stake / MANIFEST server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--players", type=int, default=2, help="2–4 crew seats at boot (ignored if --computers set)")
    parser.add_argument(
        "--computers",
        type=int,
        default=0,
        help="Computer opponents at boot (0–3). Seat 0 = Pilot (human pad).",
    )
    parser.add_argument(
        "--game",
        default="flip7",
        choices=("flip7", "stake", "manifest"),
        help="Boot game on the Games tab (default flip7)",
    )
    args = parser.parse_args(argv)

    n_comp = max(0, min(3, args.computers))
    if n_comp > 0:
        names, bot_seats = build_roster(computers=n_comp, game=args.game)
    else:
        n = max(2, min(4, args.players))
        names = DEFAULT_CREW[:n] if n <= len(DEFAULT_CREW) else [f"Crew {i+1}" for i in range(n)]
        bot_seats = set()

    if args.game == "stake":
        set_match(StakeLiveMatch(names, bot_seats=bot_seats), game_id="stake", computers=n_comp)
    elif args.game == "manifest":
        set_match(ManifestLiveMatch(names, bot_seats=bot_seats), game_id="manifest", computers=n_comp)
    else:
        set_match(LiveMatch(names, bot_seats=bot_seats), game_id="flip7", computers=n_comp)

    httpd = ThreadingHTTPServer((args.host, args.port), HolotableHandler)
    httpd.daemon_threads = True
    httpd.allow_reuse_address = True
    print(f"Holotable listening on http://{args.host}:{args.port}/")
    print(f"  public table:  http://{args.host}:{args.port}/")
    print(f"  datapad seat0: http://{args.host}:{args.port}/pad.html?seat=0")
    print(f"  datapad seat1: http://{args.host}:{args.port}/pad.html?seat=1")
    print(f"  websocket:     ws://{args.host}:{args.port}/ws?role=table")
    print(f"  active game:   {args.game}")
    print(f"  computers:     {n_comp}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutdown")
    finally:
        _cancel_bot_timer()
        httpd.server_close()


if __name__ == "__main__":
    main()
