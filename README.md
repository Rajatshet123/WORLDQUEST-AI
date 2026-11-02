# WORLDQUEST AI

A persistent community driven fantasy world for Twitch streams. React/Vite powers the creator dashboard and OBS overlay; FastAPI, SQLite and WebSockets power world state and chat commands.

## Local demo

The frontend works on its own with simulated local controls. It always labels demo activity as simulated and distinct from Twitch chat. To connect the persistent API, install Python 3.11+ and follow the backend steps below.

### Windows PowerShell

First install Python 3.11 or newer from [python.org](https://www.python.org/downloads/windows/) if `py -3 --version` does not show an installed version. From the project folder, run these PowerShell commands in order:

```powershell
# Create a project-local virtual environment so dependencies stay out of system Python.
py -3 -m venv .venv
# Activate that environment for this PowerShell session.
.\.venv\Scripts\Activate.ps1
# Install FastAPI, SQLite-adjacent helpers, the Twitch HTTP/WebSocket clients, and dotenv.
pip install -r backend\requirements.txt
# Create the local secrets/config file from the safe, blank template.
Copy-Item .env.example .env
# Start the development API on localhost:8000.
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

The Vite development server runs separately:

```powershell
# Install the React/Vite dependencies listed in package.json.
npm install
# Start the dashboard at http://localhost:5173.
npm run dev
```

Open `http://localhost:5173`. API health and persistent state are at `http://localhost:8000/api/health` and `/api/state`. The app attempts to attach to the API and WebSocket automatically; without an API it remains a clearly marked, interactive frontend demo.

## Twitch setup

Create a Twitch application and set its OAuth redirect URL to `http://localhost:8000/auth/twitch/callback`. Put its Client ID and Client Secret in the root `.env` file. Start the backend and select **Connect Twitch** in the dashboard. Authorization uses the backend Authorization Code Flow with a one-time state value. The backend holds tokens in process memory and subscribes to `channel.chat.message` over EventSub WebSocket after authorization. This local MVP needs the channel broadcaster to authorize and use chat; production deployments need durable token encryption, refresh handling, HTTPS, and deployment-specific callback URLs.

## AI story generation

Set `OPENAI_API_KEY` in the backend `.env`. The `/api/story` endpoint sends a concise structured generation request to OpenAI and saves the returned quest in SQLite. Without a key, it returns a clear configuration error and the deterministic game commands continue to work. The key is never served to the browser.

## Commands

`!join`, `!status`, `!quest`, `!vote 1`, `!vote 2`, `!attack`, `!heal`, `!leaderboard`, and `!world`. Chat messages are persisted in `world_history`; player records, one vote per player, active quests, and boss HP are stored in SQLite. The dashboard overlay is available at `/overlay` and is sized to float on OBS scenes.

## API

- `GET /api/health`, `GET /api/state`
- `POST /api/command` (`{"username":"DemoHero","message":"!join"}`)
- `POST /api/demo/event` (the same shape; disabled when `DEMO_MODE=false`)
- `POST /api/story` (`{"prompt":"..."}`)
- `GET /auth/twitch`, `GET /auth/twitch/callback`, `POST /auth/twitch/disconnect`
- `WS /ws` (state snapshots and live update events)

No deployment is configured.
