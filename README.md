# Country Guessing Game — Backend

> REST API + WebSocket backend for the Country Guessing Game.

Built with FastAPI, PostgreSQL, and Redis. Powers real-time multiplayer matches, authentication, leaderboards, and XP/rank progression.

**Live API:** Deployed on Fly.io (integrated with frontend at [country-guessing-game-five.vercel.app](https://country-guessing-game-five.vercel.app/))

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI 0.111 |
| Database | PostgreSQL (via asyncpg + SQLAlchemy 2.0) |
| Cache | Redis 5 |
| Auth | JWT (python-jose) + bcrypt |
| Migrations | Alembic |
| Real-time | WebSockets (native FastAPI) |
| Runtime | Python 3.11+ |

## Features

- **JWT authentication** — register, login, refresh tokens
- **Matchmaking queue** — rank-based pairing with Redis
- **Real-time multiplayer** — WebSocket game handler with reconnect support
- **XP & Rank system** — points, levels, rank tiers (Bronze → Challenger)
- **Leaderboard** — global rankings + player position
- **8 question modes** — classic, hint-based, flag quiz, capitals, speed round, daily challenge, continent study, multiplayer
- **Forfeit & abandon** — graceful match termination with rewards

## Getting Started

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Redis 6+

### Installation

```bash
# Clone the repo
git clone https://github.com/YOURUSERNAME/country-guessing-game-backend.git
cd country-guessing-game-backend

# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate      # Windows
source venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your database, Redis, and secret key values
```

### Database Setup

```bash
alembic upgrade head
```

### Running

```bash
# Development
uvicorn app.main:app --reload

# Production
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

API docs at `http://localhost:8000/docs` (development only).

## Environment Variables

Copy `.env.example` to `.env` and fill in your values:

| Variable | Description |
|---|---|
| `SECRET_KEY` | JWT signing secret — generate with `openssl rand -hex 32` |
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `ALLOWED_ORIGINS` | Comma-separated list of allowed frontend URLs |
| `APP_ENV` | `development` or `production` |

## Project Structure

```
app/
├── api/v1/
│   └── endpoints/     # auth, users, matchmaking, leaderboard
├── core/              # config, security, dependencies
├── db/                # database + Redis connections
├── models/            # SQLAlchemy models
├── schemas/           # Pydantic schemas
├── services/          # question generation, rank calculation
└── ws/                # WebSocket handlers (game, manager)
alembic/               # Database migrations
```

## API Overview

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/auth/register` | Create account |
| POST | `/api/v1/auth/login` | Login, get tokens |
| POST | `/api/v1/matchmaking/queue` | Join matchmaking queue |
| DELETE | `/api/v1/matchmaking/queue` | Leave queue |
| POST | `/api/v1/matchmaking/match/{id}/forfeit` | Forfeit a match |
| GET | `/api/v1/leaderboard/global` | Global leaderboard |
| WS | `/ws/match/{match_id}` | Game WebSocket |

## Related

- [Frontend — Country Guessing Game](https://github.com/BeyzaAkgun/Country-Guessing-Game)

## License

This project is publicly visible for portfolio purposes.
Not licensed for reuse or redistribution.