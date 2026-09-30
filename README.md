# Holotable

The app is **Holotable**. **Flip 7**, **Spike**, and **MANIFEST** are games on it. The public table has five stations: Weather, Nav, Games, Bio, and Comms. Private datapads drive the active game.

Software only in this repo — no physical Pepper’s Ghost hardware, actuators, or MQTT.

## Holotable and its games

| Layer | What it is |
| --- | --- |
| **Holotable** | The app. Public table: **WEATHER · NAV · GAMES · BIO · COMMS** (keys `1`–`5`). Black / teal / hazard chrome for Pepper’s Ghost demos (**Ohio Outpost // Sol-3**). |
| **Flip 7** | A game on the Games tab. Deck and scoring are Flip 7. Action cards show as Containment Lock, Overcharge Pulse, and Neutralizer Shield. Race to **200**. The game id stays `flip7`. |
| **Spike** | A game on the same Games tab: +/- cards, goal near **0**, bomb-out if \|sum\| > 23, race to **100**. |
| **MANIFEST** | A game on the same Games tab. Original. Sell one hand card, name it, buyer pays 2. Optional look for 1. Highest coins + market after 8 rounds, or when the table ends the game. |
| **Other stations** | Polished **MOCK** stubs (solar/Kp, Earth/ISS orbit, vials SP-01–SP-08, frequency dial). Live APIs optional later. |

## Run — terminal Flip 7

```bash
python3 -m holotable
python3 -m holotable --players 4
```

## Run — Holotable server

```bash
python3 -m holotable.server
# optional: --host 0.0.0.0 --port 8766 --players 3 --game spike
```

Then open:

```
# public Holotable (stations 1–5; Games = the one game menu)
http://127.0.0.1:8766/
http://127.0.0.1:8766/index.html#REACTOR
http://127.0.0.1:8766/public.html          # redirects to the Games tab

# private datapads (one tab/device per seat)
http://127.0.0.1:8766/pad.html?seat=0
http://127.0.0.1:8766/pad.html?seat=1
```

Sync: **WebSocket** `ws://127.0.0.1:8766/ws?role=table|pad&seat=N` with REST fallback (`GET /api/state`, `POST /api/hit|stay|new|game`).

### Solo with computer opponents

1. Start the Holotable server (optionally with bots at boot):
   ```bash
   python3 -m holotable.server --host 0.0.0.0 --port 8766
   # or: python3 -m holotable.server --computers 2
   ```
2. Open the public table → **Games**, or your datapad (`pad.html?seat=0`).
3. Tap **Computers: 0 / 1 / 2 / 3** (starts a new match: you = Pilot at seat 0; bots = COSMOS, F.R.A.N.K., Probe-7).
4. Play from **pad seat 0** only — bots auto-act on their turn (no phone pad).

REST: `POST /api/computers` with `{"computers":2}`. WebSocket: `{"type":"set_computers","computers":2}`.

### Switch games

- On the **Games** tab (or datapad): choose **Flip 7**, **Spike**, or **MANIFEST** from the one menu.
- REST: `POST /api/game` with `{"game":"spike"}`, `{"game":"flip7"}`, or `{"game":"manifest"}`.
- WebSocket: `{"type":"set_game","game":"manifest"}`.
- Boot: `python3 -m holotable.server --game spike` or `--game manifest`.

### MANIFEST

Original goods game on the same seats and server. No second process. Card faces are `{id, name}` so a picture can replace the label later.

- **Players:** 2–4. Each starts with **5 coins**, **3 face-up market cards**, **3 hand cards**.
- **Goods only:** Helion, plant canisters, books, antiques, star charts.
- **Turn:** sell one card from your hand to another player. Name it before they pay. They pay **2**.
- **Look:** they may pay **1** to look. No look: the sale stands as named. Match: it stands. Miss: the sale fails and the seller pays **3**, or whatever they have.
- **Draw:** the seller draws back to 3. Used cards go back under the deck.
- **Score:** coins + market. One card **2**, a pair **6**, three of a kind **10**. Highest wins after **8** rounds, or when the table ends the game.
- **Side:** merchant, smuggler, pirate, or scavenger — you pick. Nobody is assigned one. It does not change the sale.
- **Pads:** `pad.html?seat=0` and `pad.html?seat=1`. Hands stay on that datapad. The public table shows markets, coins, and the named sale.

REST: `POST /api/sell` `{"seat","card","claim","buyer"}`, `POST /api/look` `{"seat","look":true|false}`, `POST /api/end`, `POST /api/role` `{"seat","role"}`. WebSocket types: `sell`, `look`, `end`, `set_role`.

### Static-only (UI chrome, no engine)

```bash
cd holotable/web && python3 -m http.server 8766
# public: http://127.0.0.1:8766/public.html
# pad:    http://127.0.0.1:8766/pad.html
```

Without `holotable.server`, pads cannot drive real draws — use the Holotable server for play.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Rules — Flip 7 (summary)

- Deck: one `0`; card `N` appears `N` times for `N = 1..12`; three each of `SECOND_CHANCE`, `FREEZE`, `FLIP_THREE`.
- Hit draws; duplicate nonzero number **busts** (0) unless Neutralizer Shield (`SECOND_CHANCE`) absorbs once.
- Containment Lock (`FREEZE`) banks numeric score and ends the turn.
- Overcharge Pulse (`FLIP_THREE`) forces three draws.
- Seven unique numbers → `sum + 15` (**Flip 7**) and end the turn.
- First to **200** wins.

## Rules — Spike

- **Players:** 2–4.
- **Deck:** two copies of each integer from **−10..−1** and **+1..+10**, plus two **Null** cards (value **0**). 42 cards.
- **Goal:** end your turn with a hand total as close to **0** as possible.
- **Deal:** two opening cards each turn; then **Draw** (hit) or **Stand** (stay).
- **Bomb-out:** if `|hand total| > 23` after any draw, you bust and score **0** for the turn.
- **Stand scoring:** `24 − |total|` (so exact **0** / Pure Spike = **24** points).
- **Match:** first to **100** wins.
- Actions reuse the same datapad Hit / Stay buttons and `/api/hit` · `/api/stay` endpoints.

## Holotable UX (UI pass)

Games tab and datapad polish for kiosk / dark-room viewing:

- **Table:** match HUD (game · turn · race target), clearer crew piles with **TURN** badge, higher teal/orange contrast.
- **Pad:** large Hit/Stay targets, **Your turn** banner, help collapsed under details.
- **Games tab:** one menu for Flip 7, Spike, and MANIFEST. Score card: number tiles, player totals, Bonus row.

Details: `holotable/BRIDGE.md` (UX notes).

## Architecture

- `holotable/` — the app package. Flip 7 lives in `deck`, `game`, `turn`, and `live` (the game is still Flip 7; its id is `flip7`). Spike (`spike`, `spike_live`), MANIFEST (`manifest`, `manifest_live`), computer opponents (`bots`), and `server` (`python -m holotable.server`).
- `holotable/web/` — Holotable static UI (`index.html`, `pad.html`, `css/`, `js/`).
- See `holotable/BRIDGE.md`.

The GitHub repository is still named `flip-7`. It should be renamed to `holotable` after Jonathan confirms. This change does not rename the repository.

## Roadmap / out of scope here

- [x] Terminal multiplayer rules engine
- [x] Holotable five-station shell + Flip 7 on the Games tab
- [x] Spike and MANIFEST on that same Games tab
- [x] MANIFEST on the same Holotable server
- [x] Computer opponents (solo / fill seats; server-driven)
- [ ] Godot 4 table UI / Pepper’s Ghost layout (phase 2)
- [ ] Physical Pepper’s Ghost, Holotable station hardware, actuators, MQTT / Home Assistant
- [ ] Live WEATHER / NAV data feeds

Owner: Jonathan Sarkkinen (`JonaSkinny1`)
