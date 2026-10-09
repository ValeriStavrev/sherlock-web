# Sherlock Web

A free, no-login web interface for public OSINT. It has two deliberately separate modes:

- **Username** — the existing Sherlock username engine.
- **Email** — passive DNS + Socialscan + breach OSINT. It does **not** automatically run the candidate username through Sherlock.

The email local-part is shown only as a **Candidate username**. If you want to investigate it, switch to Username mode and start a separate scan yourself.

## Email sources

The email mode deliberately uses separate modules for separate questions:

1. **Socialscan 2.0.1** checks whether the email is associated with an account on supported platforms. It supports email checks for services including GitHub, Instagram, Twitter/X, Tumblr, Last.fm, Pinterest and Firefox. Socialscan is MPL-2.0.
2. **XposedOrNot** checks the email against its breach index. Its basic `/v1/check-email/{email}` endpoint currently requires no API key and has published free-tier rate limits of 2 requests/second, 25/hour and 100/day per IP.
3. **DNS/MX** via dnspython.
4. **Optional HIBP API**. HIBP's direct email-breach API requires an API key, so it is not a required dependency.

### Why h8mail was removed

h8mail was not a good sole dependency for the free web version. It is a framework around multiple external sources, and its useful breach results depend on which source is configured and available. In particular, its HIBP integration requires an HIBP API key. A successful h8mail process therefore does not necessarily mean that it can return breach names for an arbitrary email.

The new stack gives the app a dedicated free breach endpoint (XposedOrNot) and a separate email-account OSINT engine (Socialscan). If either source fails, the UI reports that source as unavailable instead of treating the email as clean.

## Local Windows

Requirements: Python 3.10+ recommended. Do **not** install or select a specific Python 3.13 runtime just for this project.

1. Extract the project.
2. Run `run_windows.bat`.
3. The script creates `.venv`, installs the dependencies and starts the app.
4. Open `http://127.0.0.1:5000`.

If Python is missing, install a current Python 3 release and make sure the Python launcher/`python` command is available.

Manual setup:

```powershell
py -3 -m venv .venv
.venv\\Scripts\\python.exe -m pip install --upgrade pip
.venv\\Scripts\\python.exe -m pip install -r requirements.txt
.venv\\Scripts\\python.exe serve.py
```

## Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python serve.py
```

## Docker

```bash
cp .env.example .env
# edit .env if desired
docker compose up -d --build
```

The container listens on port `5000`.

For a public deployment, put HTTPS/reverse-proxy infrastructure in front of the container and forward traffic to port 5000.

## Environment variables

Copy `.env.example` to `.env`.

- `DONATE_URL` — optional donation destination.
- `MAX_JOBS` — concurrent scanner jobs.
- `RATE_LIMIT_COUNT` / `RATE_LIMIT_WINDOW` — basic per-IP start limit.
- `SHERLOCK_TIMEOUT` - compatibility timeout. Fast/full scans use `SHERLOCK_FAST_TIMEOUT` and `SHERLOCK_FULL_TIMEOUT`.
- `SOCIALSCAN_TIMEOUT` — Socialscan timeout.
- `XON_TIMEOUT` — XposedOrNot timeout.
- `HIBP_TIMEOUT` — optional HIBP timeout.
- `HIBP_API_KEY` — optional official HIBP API key. Email scanning still works without it.
- `PORT` — application port.
- `WAITRESS_THREADS` — production WSGI thread count.

Never commit `.env` or API keys.

## Privacy / safety

- No login or registration.
- No scan-history database.
- Email addresses are kept only in the in-memory job until it expires.
- No passwords or raw breach records are returned to the frontend.
- User input is validated before scanner execution.
- Scanner commands use argument arrays rather than shell strings.
- Individual email sources can fail without crashing the whole scan.
- The app does not log into accounts or bypass CAPTCHAs, Cloudflare, rate limits or authentication.

## Username mode vs Email mode

They are intentionally independent:

```text
Username mode
    username -> Sherlock -> username results

Email mode
    email -> DNS + Socialscan + XposedOrNot (+ optional HIBP) -> email results
             |
             +-> candidate username shown only as a possible pivot
```

The email scan does **not** automatically run Sherlock. This prevents the email results page from mixing two different investigations.

## Health check

After starting the server:

```text
http://127.0.0.1:5000/healthz
```

It reports whether Sherlock and Socialscan are installed and whether an HIBP key is configured.

## Responsible use

This project is for lawful public-information research and security/OSINT work. Respect applicable law, privacy rights, and the terms/rate limits of external services.


## Username scan speed

The web UI defaults to **Fast scan**, which checks a curated set of high-value platforms instead of waiting on the entire Sherlock dataset. **Full scan** is available when broader coverage is more important than speed.

The per-site timeout is intentionally short so a dead or blocking site cannot make a search sit for many minutes. A slow site may therefore appear as unavailable rather than delaying the whole scan.
