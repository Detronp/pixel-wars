# 🎮 Pixel Wars

A shared, real-time pixel canvas (think r/place) built with **Flask**, **Redis** and **Nginx**, and
run as a small multi-container cluster with **Docker Compose**.

Everyone paints on the same 64×64 board. Each player gets one pixel every few seconds. Open two
browser windows and watch them stay in sync.

## Architecture

```
            ┌──────────────┐
 browser ──▶│   nginx :80  │  rate limiting, gzip, load balancing
            └──────┬───────┘
         ┌─────────┼─────────┐
         ▼         ▼         ▼
     ┌───────┐ ┌───────┐ ┌───────┐
     │ web 1 │ │ web 2 │ │ web 3 │  Flask + gunicorn (stateless)
     └───┬───┘ └───┬───┘ └───┬───┘
         └─────────┼─────────┘
                   ▼
             ┌──────────┐
             │  redis   │  board, version counter, cooldowns (persisted to a volume)
             └──────────┘
```

- The app containers keep no state, so you can scale them up and down freely.
- Every response carries an `X-Served-By` header. The **Cluster** panel on the page charts which
  replica answered each request, so you can watch the load balancing happen.
- Clients poll `/api/board?since=<version>`. When nothing changed, the server replies with an
  empty `204`, so idle clients cost almost nothing.

## Quick start

```bash
cp .env.example .env          # optional: set PORT and ADMIN_TOKEN
docker compose up -d --build
open http://localhost:8080    # or just visit it in your browser
```

Check the health of every container:

```bash
docker compose ps             # every service should show (healthy)
docker compose logs -f nginx  # see which replica ($upstream_addr) handled each request
```

## Things to try

| Try this | What happens |
|---|---|
| `docker compose up -d --scale web=5` | Two more replicas appear in the Cluster panel within about 10s |
| `docker compose stop web` then `start web` | The page shows "reconnecting…" and then recovers |
| `docker compose restart redis` | The board survives, because Redis writes to the `redis-data` volume |
| `docker compose down -v` | Wipes the board along with the volume |
| `curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" localhost:8080/api/reset` | Clears the board |

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/board?since=N` | Full board (`pixels` is a 4096-character hex string), or `204` if it hasn't changed |
| POST | `/api/pixel` | `{"x": 0-63, "y": 0-63, "c": 0-15}`. Returns `429` with `retry_in` during cooldown |
| GET | `/api/stats` | Total pixels placed, replica name and uptime |
| POST | `/api/reset` | Clears the board. Needs the `X-Admin-Token` header |
| GET | `/healthz` | Checks the Redis connection; returns `503` if Redis is down |

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8080` | Host port Nginx listens on |
| `COOLDOWN_SECONDS` | `3` | Seconds between pixels for each player |
| `ADMIN_TOKEN` | *(empty)* | Turns on `/api/reset` when set |
| `REDIS_URL` | set in compose | Without it, the app falls back to in-memory storage |

## Local development (no Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
flask --app app run --debug   # uses the in-memory store
pytest -q
```

## CI/CD

`.github/workflows/ci.yml` runs the tests on every push and pull request. On pushes to `main` it
also builds the image and publishes it to `ghcr.io/<you>/<repo>`.
