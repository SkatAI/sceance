# Inigo Voice Agent — Web Deployment Spec

## What we're building
A publicly accessible page at voice.alexisperrier.com with a landing
page and a "Talk to the Coach" button that starts a real-time voice
conversation with the Inigo agent via WebRTC.

## Architecture overview

```
[Browser]                    [Daily.co]              [Droplet]
    |                            |                       |
    |  1. GET landing page       |                       |
    |<--------------------------------------------------------|
    |                            |                       |
    |  2. Click button           |                       |
    |  3. POST /start-session -------------------------------->|
    |  4. Response: {room_url, token}  <-----------------------|
    |                            |                       |
    |  5. Connect to Daily room  |                       |
    |--------------------------->|                       |
    |                            |  6. Bot joins room    |
    |                            |<----------------------|
    |                            |                       |
    |  7. Audio flows via Daily  |                       |
    |<=========================>|<======================>|
```

## Tech stack
- Frontend: static HTML + vanilla JS (no framework)
- Backend: FastAPI (Python 3.11+) running the Pipecat pipeline
- WebRTC transport: Daily.co (Pipecat's default transport)
- TTS: Cartesia
- STT: Deepgram
- LLM: Anthropic (configurable via env var)
- Hosting: DigitalOcean Droplet (Ubuntu 24.04)
- Reverse proxy: nginx with Let's Encrypt SSL
- Process manager: systemd service for the Pipecat server
- Domain: voice.alexisperrier.com (A record → Droplet IP)

## Repository layout
inigo-voice/
  .env.example
  requirements.txt
  README.md
  src/
    server.py          # FastAPI: serves landing page + /start-session
    bot.py             # Pipecat pipeline assembly
    prompt.py          # Inigo system prompt (v3)
  static/
    index.html         # Landing page
    style.css          # Minimal styling
    app.js             # Daily.co WebRTC client logic
  deploy/
    nginx.conf         # nginx site config for voice.alexisperrier.com
    inigo.service       # systemd unit file

## Frontend — static/index.html

A single page with:
- A short text introducing Inigo (2-3 sentences max)
- A prominent "Talk to the Coach" button
- A connection status indicator (connecting / connected / ended)
- A "Hang up" button (visible only when connected)
- No chat transcript, no text input, no visual clutter
- Mobile-first responsive design — this will mostly be used on phones
- Dark, calm aesthetic — no bright colors, no animations

Interaction flow:
1. Page loads. Button is visible and ready.
2. User taps "Talk to the Coach".
3. JS calls POST /start-session on the backend.
4. Backend creates a Daily room, spawns the bot into it, returns
   {room_url, token} to the browser.
5. JS uses the Daily client SDK (daily-js, loaded from CDN) to join
   the room with the token. Browser prompts for microphone permission
   at this point (the tap on the button is the user gesture that
   satisfies the browser's autoplay policy).
6. UI transitions to "connected" state — button changes to "Hang up",
   status indicator shows connected.
7. Audio flows. Inigo greets the caller.
8. User taps "Hang up" or closes the tab → Daily room is destroyed,
   bot process ends.

daily-js import: use the CDN script tag, not npm.
  <script src="https://unpkg.com/@daily-co/daily-js"></script>

## Backend — src/server.py

FastAPI app with two responsibilities:

1. Serve the static landing page (mount static/ directory)

2. POST /start-session endpoint:
   - Creates a Daily room via Daily REST API
     (https://api.daily.co/v1/rooms) with a short expiry (30 min)
   - Creates a meeting token for the room
   - Spawns the Pipecat bot (bot.py) as a subprocess or async task,
     configured to join that room
   - Returns {room_url, token} as JSON to the browser
   - Error handling: if room creation fails, return 500 with message

3. Rate limiting: simple in-memory counter, max 5 concurrent sessions.
   Return 429 if exceeded. This prevents runaway costs during testing.

## Backend — src/bot.py

Pipecat pipeline, same as your current local bot but configured for
production:

- Transport: DailyTransport, joining the room URL passed as argument
- STT: Deepgram (nova-2)
- LLM: Anthropic Claude (or OpenAI, via env var)
- TTS: Cartesia, voice ID from env var
- System prompt: imported from prompt.py
- Bot speaks first after connection is established: uses the Inigo
  opening greeting from the system prompt
- Pipeline: transport.input → STT → LLM context → LLM → TTS →
  transport.output
- On participant leave or room timeout: bot cleans up and exits
- Logging: per-turn latency metrics (STT finalize time, LLM TTFT,
  TTS TTFB) to stdout — captured by systemd journal

## Backend — src/prompt.py

Module-level constant SYSTEM_PROMPT containing the Inigo v3 prompt.
Provided separately — do not generate.

## Configuration — .env.example

```
# Daily.co
DAILY_API_KEY=

# Deepgram
DEEPGRAM_API_KEY=

# LLM
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
LLM_MODEL=claude-sonnet-4-20250514

# Cartesia
CARTESIA_API_KEY=
CARTESIA_VOICE_ID=

# Server
HOST=0.0.0.0
PORT=8001
MAX_SESSIONS=5
```

## Deployment — DigitalOcean Droplet

### DNS
- A record: voice.alexisperrier.com → Droplet IP

### Droplet setup
- Ubuntu 24.04, minimum 2GB RAM / 1 vCPU
- Python 3.11+ via apt or pyenv
- nginx as reverse proxy
- certbot for Let's Encrypt SSL on voice.alexisperrier.com

### nginx config (deploy/nginx.conf)
```nginx
server {
    listen 443 ssl;
    server_name voice.alexisperrier.com;

    ssl_certificate /etc/letsencrypt/live/voice.alexisperrier.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/voice.alexisperrier.com/privkey.pem;

    # Static files
    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # WebSocket support (if needed for future transports)
    location /ws {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}

server {
    listen 80;
    server_name voice.alexisperrier.com;
    return 301 https://$server_name$request_uri;
}
```

### systemd service (deploy/inigo.service)
```ini
[Unit]
Description=Inigo Voice Agent
After=network.target

[Service]
Type=simple
User=inigo
WorkingDirectory=/home/inigo/inigo-voice
ExecStart=/home/inigo/inigo-voice/venv/bin/uvicorn src.server:app --host 127.0.0.1 --port 8001
Restart=always
RestartSec=5
EnvironmentFile=/home/inigo/inigo-voice/.env

[Install]
WantedBy=multi-user.target
```

## Daily.co setup (manual, one-time)
- Create a free Daily.co account at https://www.daily.co
- Get your API key from the dashboard
- Free tier includes 2,000 participant-minutes/month — more than
  enough for testing
- No rooms need to be pre-created; the server creates them on demand

## Acceptance criteria
1. voice.alexisperrier.com loads over HTTPS, shows landing page
2. Tapping "Talk to the Coach" connects and Inigo greets the caller
3. Conversation flows naturally — STT → LLM → TTS round-trip
4. "Hang up" ends the session cleanly
5. Latency metrics visible in journalctl logs
6. Works on iPhone Safari, Android Chrome, desktop browsers
7. Second concurrent user can connect (up to MAX_SESSIONS)
8. Session cleans up after tab close / timeout

## Cost estimate (testing phase)
- DigitalOcean Droplet: ~$12-24/month
- Daily.co: free tier (2,000 min/month)
- Deepgram: free tier covers testing
- Cartesia: depends on plan, ~$0.02-0.06/min
- Anthropic: ~$0.01-0.03/min depending on prompt length
- Domain/SSL: free (existing domain + Let's Encrypt)

Total for light testing: $15-30/month + per-minute AI costs
```
