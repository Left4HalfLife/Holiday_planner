# Away - Holiday Planner & AI Packing Assistant

A self-hosted, single-user travel planner built with Flask, SQLite, and plain
HTML/CSS/JavaScript. White-and-blue light mode, dark mode, responsive layouts,
and no hosted frontend dependencies. Your first visit starts with a clean slate.

## Start with Docker

Install Docker with the Docker Compose plugin, then run from this directory:

```sh
cp .env.example .env
docker compose up --build
```

Open **http://localhost:5000**. SQLite tables are created automatically at
`/app/data/holidays.db`, persisted in `./data` on the host. No database commands,
external database service, or API account are required. The app also starts
without `.env`, using the defaults in Compose.

The container initializes ownership of its database files and runs Gunicorn as
an unprivileged user (UID 10001). Keep `data/` dedicated to this application.
Use `docker compose up -d --build` to run in the background, `docker compose logs -f`
for logs, and `docker compose down` to stop. Stopping or rebuilding preserves data.

## Connect LM Studio

1. Load a chat/instruct model in LM Studio and start the OpenAI-compatible server
   (usually in **Developer / Local Server**) on port **1234**.
2. Enable **Serve on Local Network** so the Docker container can reach it.
   Restrict firewall access to trusted local/Docker networks. Do not expose the
   model server to the internet.
3. Configure `.env`:
   - `LLM_BASE_URL=http://host.docker.internal:1234/v1`
   - `LLM_API_KEY=lm-studio`, or your actual token if authentication is enabled.
   - `LLM_MODEL=` selects the first model reported by `/v1/models`. To select a
     specific model, use its exact ID.
4. Recreate the application after changing settings: `docker compose up -d`.
   Click the **AI: Online/Offline** badge to recheck and see connection details.

Compose includes `host.docker.internal:host-gateway` for Linux; Docker Desktop
also supports the host alias. When running Flask directly on the same machine
as LM Studio, use `http://127.0.0.1:1234/v1` instead.

**CORS:** Flask calls LM Studio server-to-server; the browser never calls it
directly or receives the API key, so LM Studio CORS is **not required** here.
If separately testing the LM Studio API from a browser, enable its **CORS**
setting for that trusted origin. CORS does not replace local-network access or
firewall configuration.

Use a model supporting `response_format: {"type": "json_object"}`. The app sends
bounded structured action requests, not arbitrary code or SQL. Invalid JSON,
unsupported actions, missing targets, or invalid field values reject the entire
transaction. If a model ignores JSON instructions, switch to a capable instruct
model. AI requests can take up to 90 seconds; core editing remains independent.
There is no hosted AI fallback. Offline failures are explicit and do not insert
pretend AI results.

## What you can do

- Create, edit, and delete holidays with destinations, inclusive departure/return
  dates, accommodation, booking references, notes, and travel conditions.
- Switch between grouped **Active / Upcoming / Past cards** and a monthly
  calendar with multi-day spans. Search by title or destination; click a date
  to start a holiday. Status dates follow your browser's local date.
- Add, edit, delete, and check off categorized packing items with quantities.
  Progress counts checklist rows, not individual units.
- Track a budget and itemized expenses in one trip currency. Money is stored
  as integer cents, accepts up to two decimal places, and can go over budget.
  Changing currency is blocked while expenses exist; there is no FX conversion.
- Record multiple flight legs, local times, optional IANA time zones, terminals,
  gates, and booking codes. Unknown details can be filled in later.
- Save a packing list as a named template; load it into any holiday. Applying a
  template adds missing items unpacked and preserves existing items, quantities,
  and checkmarks. Duplicate matching uses category plus case-folded item name.
  Templates can be managed from the sidebar and survive holiday deletion.
- Export `.ics` for Apple, Google, or Outlook. Holiday end dates are inclusive in
  the UI and exclusive in ICS, as required by the format. Flight times with IANA
  zones are converted to UTC; without zones they are floating local times.
  Flights missing departure times are omitted. Incomplete or incompatible
  arrival times remain in the event description rather than inventing a duration.
- **Print itinerary** (or save to PDF) for a complete offline copy of the trip,
  packing list, bookings, flights, and budget. Print includes all packing items,
  even if a checklist filter is selected. This is not an offline-editing PWA.

### Local AI features

**Smart pack** combines a tailored AI list with essential rules: daily clothing
for the inclusive trip length, a four-day clothing rotation when laundry is
available, weather essentials, certified KN95 masks and saline spray for
moderate/high AQI, and dietary translation cards when requirements are noted.
Existing items are preserved; repeated generation skips same-name/category
duplicates rather than clearing progress. Review quantities and medical
preparations yourself.

**Trip assistant** saves conversation history and can add/update packing items,
delete packing items, add/update flights, log expenses, and update holiday
details, scoped to the current trip. For example:

- "Add 3 packs of KN95 masks and ibuprofen to my medication list."
- "Log 140 for a hotel deposit under Accommodation."
- "Add flight QF129 departing Sydney at 09:30 on November 12, 2027."

The assistant directly saves valid actions. Review its response and the refreshed
trip; it should ask for clarification instead of inventing missing details.
**Audit my trip** reviews return flights, essential packing, dietary needs,
and budget; it records advice in chat but cannot mutate itinerary data.
AI is not a source of medical, immigration, or guaranteed flight advice.

## Privacy and deployment

This is a **single-user application with no built-in authentication**. It binds
to `127.0.0.1` by default. For remote access, prefer a private VPN or an
authenticated HTTPS reverse proxy. Set `BIND_ADDRESS` only if you understand
the exposure; every person who can reach the app can read and modify all trips.
Behind a proxy, preserve the host and the scheme seen by Flask for same-origin
checks; terminate TLS at a trusted local proxy and configure forwarded headers
deliberately rather than trusting arbitrary client headers.

SQLite contains private travel, dietary, booking, and conversation data. Keep
`.env`, `data/`, and backups private; they are excluded from Git and image builds.
AI actions send current trip details and recent conversation history to the
configured endpoint. Use a local endpoint if that data must stay on your machine.
The app uses parameterized SQL, strict payload validation, same-origin JSON
write protections, escaped text rendering, and a restrictive CSP. These do not
replace authentication or network isolation.

### Back up and restore

Create a consistent SQLite backup while the app is running:

```sh
docker compose exec --user planner holiday-planner python -c \
  "import os, sqlite3; os.umask(0o077); src=sqlite3.connect('/app/data/holidays.db'); dst=sqlite3.connect('/app/data/holidays.backup.db'); src.backup(dst); dst.close(); src.close()"
docker compose cp holiday-planner:/app/data/holidays.backup.db ./holidays.backup.db
```

Store the backup securely outside the repository. For restore, stop the app,
preserve the current `data` directory as a separate backup, create a fresh
`data` directory containing the backup renamed to `holidays.db`, then start
Compose. Never replace a live database or mix it with old `-wal`/`-shm` files.

## Local development and verification

Python 3.12+ is recommended. No Node build or CDN connection is needed.

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export LLM_BASE_URL=http://127.0.0.1:1234/v1
flask --app app run --debug
python -m unittest discover -s tests -v
node --check app/static/js/app.js
```

Flask development mode reads environment variables, not `.env` automatically.
`DATABASE_PATH` overrides the default `data/holidays.db` outside Docker.
Tests use temporary databases and a local mock OpenAI-compatible HTTP server;
they do not require LM Studio, model downloads, or private travel information.
`GET /api/health` checks application/database readiness independently of AI.

## Layout

```text
app/
  __init__.py          Flask factory and request protections
  main.py              Pages and JSON API
  database.py          SQLite connections and versioned schema initialization
  validation.py        Shared manual/AI input validation
  services.py          Database operations and trip summaries
  ai_service.py        OpenAI-compatible client and atomic structured actions
  calendar_export.py   RFC 5545 calendar export
  static/              Local CSS, JavaScript, and SVG icons
  templates/           Jinja pages and forms
data/                  Persistent database (not committed)
tests/                 Isolated integration tests
```
