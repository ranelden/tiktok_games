# TikTok Game

A party game for a group of friends: everyone uploads their TikTok "liked videos" export, and each round the app picks a random liked video and asks *"who liked this?"*. Guess right (alone or in a risky multi-pick) to score points, or bet that nobody will find out it's your video.

Built with Flask + vanilla HTML/CSS/JS, SQLite, and Docker Compose behind a Caddy reverse proxy.

## Features

- **Accounts** — email/password signup (hashed with `werkzeug.security`), with your TikTok export uploaded at signup or added/refreshed later.
- **Rooms** — create a room (get a 6-character code) or join one. The room's creator ("chef") configures the game and starts it; everyone else waits in a lobby.
- **Round configuration** — number of rounds (3–20), how far back to pull liked videos from (a 10-step slider from 1 day to the entire history), and an optional per-round timer (15s/30s/60s/none).
- **Live video** — each round embeds the actual TikTok video via TikTok's official embed widget, with a plain link fallback if the embed can't load (private/deleted/region-locked video).
- **Voting** — pick one player (safe, worth 1 point) or several at once (risky: a full house pays a bonus per correct pick, but a single wrong pick in the selection turns the whole vote into a penalty).
- **Betting** — if you're the video's owner, you can bet that nobody will pick you; the fewer players who find you, the bigger the bonus.
- **Live scoreboard** — persistent score list with an animated count-up and flash on every change, a round-by-round reveal (color-coded by points gained/lost), and a podium screen at the end of the game.
- **Custom display names** — in-memory only, no DB migration needed; defaults to your email.
- **Adminer** (optional) — a lightweight web UI to inspect the SQLite database, bound to localhost by default when deployed.

## How a round works

1. The server builds a pool of every video liked by any player in the room (respecting the room's period filter), excluding videos already drawn this game.
2. A video is drawn at random and shown to everyone. Its real owner(s) — there can be more than one if several players liked the same video — stay secret.
3. Each player (including the video's owner, who may not even remember liking it) picks one or more players they think liked it. The owner may also place a bet before voting closes.
4. Once everyone has voted (or the timer runs out), the round reveals: correct guesses and bets pay out, and the persistent scoreboard updates.
5. The chef advances to the next round, or the game ends and shows the final podium.

Scoring, defined in [`app/game.py`](app/game.py):

| Action | Points |
|---|---|
| Single guess, correct | +1 |
| Multi-select, all picks correct | +2 per correct pick |
| Multi-select, any pick wrong | -1 per wrong pick |
| Bet placed as video owner | +2 per player who didn't pick you |

## Tech stack

- **Backend**: Python 3 / Flask, `sqlite3` (stdlib), sessions via signed cookies.
- **Frontend**: no framework — plain HTML/CSS/JS, split into `api.js` (fetch helpers), `auth.js`, `rooms.js`, `main.js` (view routing + rendering).
- **Database**: SQLite, two tables (`users`, `videos`) — see [Database](#database) below. Room/game state is **in-memory only** (see [Design notes](#design-notes)).
- **Infra**: Docker Compose, Caddy (reverse proxy + automatic HTTPS via Let's Encrypt when a domain is configured), optional Adminer for DB inspection.

## Project structure

```
app/
  app.py           Flask routes (auth, rooms, rounds)
  auth.py          User accounts, sessions, in-memory display names
  game.py          Room/round state machine, scoring, in-memory room registry
  parser.py        Parses the TikTok export zip into a list of liked videos
  videos.py        DB access for the videos table + slimmed-down export backup
  db.py            SQLite connection handling, schema init
  schema.sql       Database schema (users, videos)
  static/
    index.html     Single-page app shell (all screens, toggled via JS)
    style.css
    js/
      api.js       fetch() wrappers
      auth.js      Register/login/logout/upload requests
      rooms.js     Room/round requests
      main.js      View routing, rendering, all event listeners
docker-compose.yml           Base stack: Caddy + app (production-safe defaults)
docker-compose.override.yml  Local dev only (auto-loaded): hot reload, direct app port, Adminer
docker-compose.prod.yml      Optional Adminer for a real deployment (bound to localhost by default)
Caddyfile                    Reverse proxy config (auto-HTTPS if DOMAIN is set)
setup.sh                     Interactive setup script for a fresh server
```

## Getting started (local development)

Requires Docker with the Compose v2 plugin (`docker compose`, not the old standalone `docker-compose`).

```bash
cp .env.example .env
# generate a SECRET_KEY:
python3 -c "import secrets; print(secrets.token_hex(32))"
# paste it into .env

docker compose up --build
```

`docker-compose.override.yml` is picked up automatically and adds hot reload (your `app/` edits apply without rebuilding), direct access to the Flask app on `APP_PORT` (default `5000`), and Adminer on `ADMINER_PORT` (default `8081`). The app itself is served through Caddy on `HOST_HTTP_PORT` (default `80`).

## Deploying to a server

On a fresh VPS (tested for Azure, works anywhere with `apt` or `get.docker.com` support):

```bash
git clone <your-repo-url> && cd tiktok-game
./setup.sh
```

The script:
1. Installs Docker + Compose v2 if missing, and adds your user to the `docker` group.
2. Asks for a domain (optional — enables automatic HTTPS via Caddy/Let's Encrypt, requires ports 80/443 open and DNS already pointed at the server) or a plain HTTP port if you don't have one.
3. Asks whether to enable Adminer, and whether to expose it publicly or keep it reachable only via SSH tunnel (recommended — SQLite has no authentication of its own, so anyone reaching an exposed Adminer can read/write the whole database).
4. Generates `.env` with a random `SECRET_KEY`, creates the persistent `volumes/` directories, opens the relevant ports in `ufw` if it's active, and starts the stack.

Re-running `./setup.sh` after a `git pull` offers to keep your existing `.env` and just rebuild/restart.

**Not handled by the script**: your cloud provider's firewall (e.g. Azure Network Security Group) — that has to be opened from the portal/CLI separately, `ufw` only affects the VM itself.

## Configuration

Environment variables, set in `.env`:

| Variable | Default | Purpose |
|---|---|---|
| `DOMAIN` | *(empty)* | If set, Caddy requests a Let's Encrypt certificate and serves HTTPS. If empty, plain HTTP on `HOST_HTTP_PORT`. |
| `HOST_HTTP_PORT` | `80` | Host port mapped to Caddy's HTTP listener. |
| `HOST_HTTPS_PORT` | `443` | Host port mapped to Caddy's HTTPS listener. |
| `APP_PORT` | `5000` | Internal Flask port (also the port exposed directly in dev via the override file). |
| `FLASK_DEBUG` | `false` | Enables Werkzeug's debugger/reloader. **Never set to `true` on a public deployment** — it allows remote code execution on unhandled errors. |
| `SECRET_KEY` | *(required)* | Flask session signing key. Generate with `python3 -c "import secrets; print(secrets.token_hex(32))"`. |
| `ADMINER_PORT` | `8081` | Port Adminer listens on, if enabled. |
| `ADMINER_BIND` | `127.0.0.1` | (prod compose file only) Interface Adminer binds to; `0.0.0.0` exposes it publicly. |

## API reference

All routes are JSON except `/` (serves the SPA) and file uploads (`multipart/form-data`). Routes marked 🔒 require an authenticated session.

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Liveness check. |
| POST | `/api/register` | Create an account (`email`, `password`, optional `file` = TikTok export zip). Logs in on success. |
| POST | `/api/login` | `{email, password}`. |
| POST | `/api/logout` | 🔒 Clears the session. |
| GET | `/api/me` | 🔒 Current user info. |
| POST | `/api/username` | 🔒 `{name}` — update your display name. |
| POST | `/api/upload` | 🔒 Add/refresh liked videos from a new export zip (`file`, deduplicated). |
| POST | `/api/rooms` | 🔒 Create a room; caller becomes chef. |
| POST | `/api/rooms/<code>/join` | 🔒 Join an existing room. |
| GET | `/api/rooms/<code>` | 🔒 Current room/round state (also used for polling). |
| POST | `/api/rooms/<code>/config` | 🔒 Chef only. `{num_rounds, period_days, timer_seconds}`. |
| POST | `/api/rooms/<code>/start` | 🔒 Chef only. Locks config, draws round 1. |
| POST | `/api/rooms/<code>/vote` | 🔒 `{guessed_user_ids: [...]}`. |
| POST | `/api/rooms/<code>/bet` | 🔒 Video owner only, once per round. |
| POST | `/api/rooms/<code>/next` | 🔒 Chef only. Reveals→next round, or ends the game. |

## Database

Only durable per-user data lives in SQLite ([`app/schema.sql`](app/schema.sql)) — everything about an in-progress game lives in memory (see below).

```sql
users  (id, email UNIQUE, password_hash, created_at)
videos (id, user_id → users, link, liked_at, imported_at, UNIQUE(user_id, link))
```

## Design notes

- **Rooms and rounds are in-memory, not in the database.** No history of past games is kept, and a container restart clears every active room. This is intentional (simpler, and games are short-lived), but it also means **the app must run as a single process** — running multiple Flask/Gunicorn workers would split room state across processes and break the game.
- **The TikTok export backup is slimmed down** before being written to `volumes/uploads/<user_id>.zip`: only the parsed `{date, link}` pairs are kept, not the original export's unrelated sections (favorites, sounds, hashtags...). It's a disk backup only — the app never reads it back; a failed write never blocks registration/upload since the data is already in SQLite by that point.
- **A video liked by several room members is not excluded from the pool** — any of its real likers counts as a correct guess at reveal time.
- **Adminer has no authentication of its own** (SQLite doesn't support it), so it's bound to `127.0.0.1` by default in production — reach it via an SSH tunnel unless you deliberately choose to expose it.
