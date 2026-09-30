# Helios ↔ flip7 bridge

## Architecture

- **`flip7/`** Python package: Flip 7 rules (`deck`, `game`, `turn`, `live`) and Sabacc (`sabacc`, `sabacc_live`).
- **`python -m flip7.server`**: serves `holotable/` static UI, REST (`/api/*`), WebSocket (`/ws`).
- **Helios shell** (`index.html`): five stations (keys 1–5). WEATHER / NAV / BIO / COMMS are labeled mocks. Branding: **Ohio Outpost // Sol-3** / Ohio ground station.
- **REACTOR**: live match with **game picker** — `LiveMatch` (Flip 7 / Reactor Overload), `SabaccLiveMatch`, or `ManifestLiveMatch`.
- **Datapads** (`pad.html?seat=N`): private Hit / Stay (Draw / Stand in Sabacc); state synced over WebSocket (REST poll fallback).

## UX notes (holotable UI pass)

Kiosk / monitor contrast and touch-friendly controls (CSS/HTML/JS only; engine unchanged):

| Surface | Intent |
| --- | --- |
| **Table (`index.html`)** | Match HUD shows active game, whose turn (name + seat pill), and race target. Crew score list highlights the active seat with a **TURN** badge and larger pile totals. Status bar + reactor core keep high teal/orange contrast for Pepper’s Ghost / dark rooms. |
| **Game picker** | Large dual buttons (`min-height` ~4rem), **ACTIVE** badge on the selected game, `role="radiogroup"`, ignore re-taps of the current game to reduce mis-switches. |
| **Pad (`pad.html`)** | Top **Your turn / Waiting** banner; larger cards and primary Hit/Stay targets (~3.5rem); New match de-emphasized; help text tucked under `<details>`. |
| **Chrome** | Teal `#00C4AE` / `#3DFFE8` and hazard orange `#FF8C1A` on black panels with corner accents — same Helios industrial look, brighter for monitors. No Youngstown branding. |

## Game switch API

| Method | Path / message | Body |
| --- | --- | --- |
| POST | `/api/game` | `{"game":"sabacc"\|"flip7"\|"manifest", "players"?: [...], "seed"?: n}` |
| POST | `/api/sell` | MANIFEST only. `{"seat", "card", "claim", "buyer"}` — name the good, buyer pays 2 |
| POST | `/api/look` | MANIFEST buyer. `{"seat", "look": true\|false}` |
| POST | `/api/end` | MANIFEST. The table ends and scores are shown |
| POST | `/api/role` | MANIFEST label only. `{"seat", "role":"merchant"\|"smuggler"\|"pirate"\|"scavenger"}` |
| POST | `/api/new` | optional `"game"` to switch while resetting |
| WS | `set_game` | `{"type":"set_game","game":"sabacc"}` |
| WS | `sell` / `look` / `end` / `set_role` | MANIFEST actions. Pad snapshots include only that seat's hand. |
| GET | `/api/games` | lists games + `active` |
| GET | `/api/health` | includes `active_game`, `outpost` |

Snapshot always includes `rules` / `game` (`flip7`, `sabacc`, or `manifest`) so the UI can re-skin. MANIFEST public snapshots omit hand faces. `GET /api/state?seat=N` and pad WebSockets include that seat's `your_hand`.

## Out of scope (this build)

- Physical Pepper’s Ghost hardware, actuators, MQTT / Home Assistant
- Full Godot 4 port (phase 2)
- Live WEATHER/NAV APIs (stubs only)
- Official Sabacc / Lucasfilm IP (house rules only)

## Run

See root README.
