from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
MAX_JOBS = int(os.getenv("MAX_JOBS", os.getenv("MAX_CONCURRENT_JOBS", "2")))
JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", "1800"))
RATE_LIMIT_COUNT = int(os.getenv("RATE_LIMIT_COUNT", os.getenv("RATE_LIMIT_MAX_REQUESTS", "5")))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")))
SHERLOCK_TIMEOUT = int(os.getenv("SHERLOCK_TIMEOUT", "4"))
SHERLOCK_FAST_TIMEOUT = int(os.getenv("SHERLOCK_FAST_TIMEOUT", "4"))
SHERLOCK_FULL_TIMEOUT = int(os.getenv("SHERLOCK_FULL_TIMEOUT", "4"))
SHERLOCK_SAFETY_SECONDS = int(os.getenv("SHERLOCK_SAFETY_SECONDS", "100"))
SOCIALSCAN_TIMEOUT = int(os.getenv("SOCIALSCAN_TIMEOUT", "90"))
XON_TIMEOUT = int(os.getenv("XON_TIMEOUT", "20"))
EMAILREP_TIMEOUT = int(os.getenv("EMAILREP_TIMEOUT", "15"))
HIBP_TIMEOUT = int(os.getenv("HIBP_TIMEOUT", "20"))
MAX_USERNAME_LENGTH = 64
MAX_EMAIL_LENGTH = 254
DONATE_URL = os.getenv("DONATE_URL", "https://buymeacoffee.com/valeri123").strip()
HIBP_API_KEY = os.getenv("HIBP_API_KEY", "").strip()

FAST_SITES = [
    "Instagram", "Reddit", "Twitter", "GitHub", "GitLab", "TikTok", "YouTube",
    "Twitch", "Discord", "Pinterest", "LinkedIn", "Snapchat", "Telegram",
    "tumblr", "Bluesky", "threads", "Medium", "SoundCloud", "Spotify",
    "Patreon", "Kick", "Codepen", "Behance", "Dribbble", "Flickr", "Vimeo",
    "GoodReads", "Letterboxd", "Roblox", "Minecraft", "Steam Community (User)"
]

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)

jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()
active_jobs = 0
active_jobs_lock = threading.Lock()
rate_buckets: dict[str, deque[float]] = defaultdict(deque)
rate_lock = threading.Lock()


def cleanup_jobs() -> None:
    cutoff = time.time() - JOB_TTL_SECONDS
    with jobs_lock:
        stale = [job_id for job_id, job in jobs.items() if job.get("updated", 0) < cutoff]
        for job_id in stale:
            jobs.pop(job_id, None)


def check_rate_limit(ip: str) -> bool:
    now = time.time()
    with rate_lock:
        bucket = rate_buckets[ip]
        while bucket and bucket[0] <= now - RATE_LIMIT_WINDOW:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_COUNT:
            return False
        bucket.append(now)
        return True


def set_job(job_id: str, **updates) -> None:
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(updates)
            jobs[job_id]["updated"] = time.time()


def parse_result_file(path: Path) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    if not path.exists():
        return results
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("Total Websites Username Detected On"):
            continue
        if URL_RE.match(line):
            parsed = urlparse(line)
            host = parsed.netloc.lower().removeprefix("www.")
            results.append({"source": host or "Website", "status": "found", "url": line, "confidence": "confirmed", "details": "Public profile URL returned by Sherlock."})
    seen = set()
    return [item for item in results if not (item["url"] in seen or seen.add(item["url"]))]


def run_x_profile_check(username: str) -> dict | None:
    """Check X using its public syndication profile metadata endpoint.

    Sherlock's X/Twitter site definition can lag behind platform changes, so
    this small fallback keeps X coverage working independently. The endpoint
    returns structured profile metadata when the handle exists.
    """
    try:
        response = requests.get(
            "https://cdn.syndication.twimg.com/widgets/followbutton/info.json",
            params={"screen_names": username},
            timeout=5,
            headers={"User-Agent": "Sherlock-Web/1.0"},
        )
        if response.status_code != 200:
            return None
        payload = response.json()
        if not isinstance(payload, list) or not payload:
            return None
        profile = payload[0]
        if not isinstance(profile, dict):
            return None
        screen_name = str(profile.get("screen_name") or "").strip()
        if not screen_name or screen_name.casefold() != username.casefold():
            return None
        return {
            "source": "X",
            "status": "found",
            "url": f"https://x.com/{screen_name}",
            "confidence": "confirmed",
            "details": "X returned public profile metadata for this username.",
        }
    except (requests.RequestException, ValueError, TypeError, KeyError):
        return None


def run_sherlock(job_id: str, username: str, scan_mode: str = "fast") -> None:
    global active_jobs
    try:
        set_job(job_id, status="running", message=("Fast scan: checking priority sites." if scan_mode == "fast" else "Full scan: checking the complete site list."), logs=[], scan_mode=scan_mode)
        with tempfile.TemporaryDirectory(prefix="sherlock-web-") as tmp:
            output_path = Path(tmp) / "results.txt"
            timeout = SHERLOCK_FAST_TIMEOUT if scan_mode == "fast" else SHERLOCK_FULL_TIMEOUT
            cmd = [sys.executable, "-m", "sherlock_project", username, "--print-found", "--no-color", "--output", str(output_path), "--timeout", str(timeout)]
            if scan_mode == "fast":
                for site in FAST_SITES:
                    cmd.extend(["--site", site])
            proc = subprocess.Popen(cmd, cwd=BASE_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            try:
                stdout, _ = proc.communicate(timeout=SHERLOCK_SAFETY_SECONDS)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                raise TimeoutError("The scan stopped after the maximum allowed time.")

            logs = [line.strip()[-300:] for line in (stdout or "").splitlines() if line.strip()][-18:]
            if logs:
                set_job(job_id, logs=logs, message=logs[-1][-120:])
            return_code = proc.returncode
            results = parse_result_file(output_path)

            # X has changed its public endpoints several times. Keep a small
            # independent fallback so a working X account is not missed just
            # because the bundled Sherlock site definition is stale.
            x_result = run_x_profile_check(username)
            if x_result and not any(str(item.get("source", "")).casefold() in {"x", "twitter", "twitter.com"} for item in results):
                results.append(x_result)

            if return_code != 0 and not results:
                raise RuntimeError(logs[-1] if logs else "Sherlock exited with an error.")
            set_job(job_id, status="done", message=f"{scan_mode.title()} scan finished.", results=results, count=len(results), logs=logs)
    except FileNotFoundError:
        set_job(job_id, status="error", message="Sherlock is not installed. Run the setup instructions in README.md or use Docker.")
    except Exception as exc:  # noqa: BLE001
        set_job(job_id, status="error", message=str(exc)[:300] or "Unknown server error.")
    finally:
        with active_jobs_lock:
            active_jobs -= 1


def normalize_email(value: str) -> str:
    return value.strip().lower()


def dns_lookup(domain: str) -> dict:
    info = {"domain": domain, "mx": [], "mx_valid": False, "a": [], "aaaa": [], "error": None}
    try:
        import dns.resolver
        try:
            info["mx"] = sorted(str(r.exchange).rstrip(".") for r in dns.resolver.resolve(domain, "MX"))
            info["mx_valid"] = bool(info["mx"])
        except Exception:
            info["mx"] = []
        for record_type, key in (("A", "a"), ("AAAA", "aaaa")):
            try:
                info[key] = sorted(str(r) for r in dns.resolver.resolve(domain, record_type))
            except Exception:
                info[key] = []
    except ImportError:
        info["error"] = "DNS module unavailable. Install dependencies again."
    return info


def run_socialscan(email: str) -> tuple[list[dict], str | None]:
    """Check email/account association signals using Socialscan's JSON CLI."""
    with tempfile.TemporaryDirectory(prefix="socialscan-email-") as tmp:
        output_path = Path(tmp) / "socialscan.json"
        cmd = [sys.executable, "-m", "socialscan", email, "--json", str(output_path)]
        try:
            proc = subprocess.run(
                cmd,
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                timeout=SOCIALSCAN_TIMEOUT,
                check=False,
            )
        except FileNotFoundError:
            return [], "Socialscan is unavailable on this server."
        except subprocess.TimeoutExpired:
            return [], "Socialscan timed out."

        if not output_path.exists():
            message = (proc.stderr or proc.stdout or "").strip().splitlines()
            return [], message[-1][:220] if message else "Socialscan returned no result file."

        try:
            payload = json.loads(output_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return [], "Socialscan returned invalid JSON."

    rows = payload if isinstance(payload, list) else payload.get("results", []) if isinstance(payload, dict) else []
    findings: list[dict] = []
    for result in rows:
        if not isinstance(result, dict):
            continue
        name = str(result.get("platform") or result.get("platform_name") or "Unknown")
        success = str(result.get("success", "False")).lower() == "true" or result.get("success") is True
        valid = str(result.get("valid", "False")).lower() == "true" or result.get("valid") is True
        available = result.get("available")
        message = str(result.get("message") or "").strip()
        url = result.get("link")
        if not success or not valid:
            findings.append({"source": name, "status": "unavailable", "confidence": "unknown", "details": message or "The platform could not be checked reliably."})
        elif available is False or str(available).lower() == "false":
            findings.append({"source": name, "status": "found", "confidence": "confirmed", "details": "Socialscan reported the email as associated with an account.", "url": url if isinstance(url, str) and URL_RE.match(url) else None})
        else:
            findings.append({"source": name, "status": "not_found", "confidence": "confirmed", "details": "No account association was reported by Socialscan."})
    if not findings and proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip().splitlines()
        return [], message[-1][:220] if message else "Socialscan returned no usable results."
    return findings, None


def run_xposedornot(email: str) -> tuple[list[dict], str | None]:
    """Free public breach lookup; no API key is required for this endpoint."""
    try:
        response = requests.get(
            f"https://api.xposedornot.com/v1/check-email/{quote(email, safe='@.')}",
            timeout=XON_TIMEOUT,
            headers={"User-Agent": "Sherlock-Web/1.0"},
        )
    except requests.RequestException as exc:
        return [], f"Breach lookup could not be reached: {str(exc)[:160]}"

    if response.status_code == 404:
        return [], None
    if response.status_code == 429:
        return [], "Breach lookup rate limit reached. Try again later."
    if response.status_code != 200:
        return [], f"Breach lookup returned HTTP {response.status_code}."

    try:
        payload = response.json()
    except ValueError:
        return [], "Breach lookup returned invalid data."

    raw_breaches = payload.get("breaches") or []
    breach_names: list[str] = []
    for group in raw_breaches if isinstance(raw_breaches, list) else []:
        values = group if isinstance(group, list) else [group]
        for value in values:
            if isinstance(value, str) and value.strip() and value.strip() not in breach_names:
                breach_names.append(value.strip()[:160])

    findings = [
        {
            "source": name,
            "kind": "breach",
            "status": "found",
            "confidence": "confirmed",
            "details": "The email appears in a known breach record.",
        }
        for name in breach_names
    ]
    return findings, None


def run_hibp(email: str) -> tuple[list[dict], str | None]:
    if not HIBP_API_KEY:
        return [], None
    try:
        response = requests.get(
            f"https://haveibeenpwned.com/api/v3/breachedaccount/{quote(email, safe='@.')}",
            timeout=HIBP_TIMEOUT,
            headers={"hibp-api-key": HIBP_API_KEY, "user-agent": "Sherlock-Web/1.0"},
        )
        if response.status_code == 404:
            return [], None
        if response.status_code != 200:
            return [], f"HIBP returned HTTP {response.status_code}."
        findings = []
        for breach in response.json():
            name = str(breach.get("Name") or breach.get("Title") or "Unknown breach")
            findings.append({"source": name, "kind": "breach", "status": "found", "confidence": "confirmed", "details": "The email appears in a known breach record."})
        return findings, None
    except requests.RequestException as exc:
        return [], f"HIBP request failed: {str(exc)[:160]}"


def run_email_scan(job_id: str, email: str) -> None:
    global active_jobs
    try:
        local = email.rsplit("@", 1)[0]
        domain = email.rsplit("@", 1)[1]
        dns = dns_lookup(domain)
        set_job(job_id, status="running", message="Checking DNS and mail infrastructure.", dns=dns, candidate_username=local)

        findings: list[dict] = []
        errors: list[str] = []

        set_job(job_id, message="Checking email sources in parallel.")
        checks = {
            "account": run_socialscan,
            "xposedornot": run_xposedornot,
            "hibp": run_hibp,
        }
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(fn, email): name for name, fn in checks.items()}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    source_findings, source_error = future.result()
                except Exception as exc:
                    source_findings, source_error = [], f"{name} failed: {str(exc)[:160]}"
                findings.extend(source_findings)
                if source_error:
                    errors.append(source_error)

        account_results = [f for f in findings if f.get("kind") != "breach"]
        breach_results = [f for f in findings if f.get("kind") == "breach"]
        account_found = sum(1 for f in account_results if f.get("status") == "found")
        breach_count = len(breach_results)

        # De-duplicate while preserving source order.
        unique: list[dict] = []
        seen = set()
        for finding in findings:
            key = (finding.get("source"), finding.get("status"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(finding)

        set_job(
            job_id,
            status="done",
            message="Email scan finished." if not errors else "Email scan finished with unavailable sources.",
            email=email,
            domain=domain,
            dns=dns,
            candidate_username=local,
            email_results=unique,
            account_results=[f for f in unique if f in account_results],
            breach_results=[f for f in unique if f in breach_results],
            account_found=account_found,
            breach_count=breach_count,
            source_errors=errors,
            logs=[],
        )
    except Exception as exc:  # noqa: BLE001
        set_job(job_id, status="error", message=str(exc)[:300] or "Email scan failed.")
    finally:
        with active_jobs_lock:
            active_jobs -= 1


@app.get("/")
def index():
    return render_template("index.html", donate_url=DONATE_URL)


@app.get("/api/config")
def config():
    return jsonify({"donate_url": DONATE_URL})


@app.post("/api/search")
def search():
    global active_jobs
    cleanup_jobs()
    ip = request.remote_addr or "unknown"
    if not check_rate_limit(ip):
        return jsonify({"error": "Too many searches. Please try again in a few minutes."}), 429
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    scan_mode = str(data.get("scan_mode", "fast")).lower()
    if scan_mode not in {"fast", "full"}:
        scan_mode = "fast"
    if not username:
        return jsonify({"error": "Enter a username."}), 400
    if len(username) > MAX_USERNAME_LENGTH or not USERNAME_RE.fullmatch(username):
        return jsonify({"error": "Username may contain only letters, numbers, dots, underscores, and hyphens."}), 400
    with active_jobs_lock:
        if active_jobs >= MAX_JOBS:
            return jsonify({"error": "The server is busy. Please retry shortly."}), 503
        active_jobs += 1
    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {"id": job_id, "mode": "username", "status": "queued", "message": "Queued.", "scan_mode": scan_mode, "results": [], "count": 0, "logs": [], "created": time.time(), "updated": time.time()}
    threading.Thread(target=run_sherlock, args=(job_id, username, scan_mode), daemon=True).start()
    return jsonify({"job_id": job_id}), 202


@app.post("/api/email-search")
def email_search():
    global active_jobs
    cleanup_jobs()
    ip = request.remote_addr or "unknown"
    if not check_rate_limit(ip):
        return jsonify({"error": "Too many searches. Please try again in a few minutes."}), 429
    data = request.get_json(silent=True) or {}
    email = normalize_email(str(data.get("email", "")))
    if not email:
        return jsonify({"error": "Enter an email address."}), 400
    if len(email) > MAX_EMAIL_LENGTH or not EMAIL_RE.fullmatch(email):
        return jsonify({"error": "Enter a valid email address."}), 400
    with active_jobs_lock:
        if active_jobs >= MAX_JOBS:
            return jsonify({"error": "The server is busy. Please retry shortly."}), 503
        active_jobs += 1
    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {"id": job_id, "mode": "email", "status": "queued", "message": "Queued.", "email": email, "dns": {}, "candidate_username": email.rsplit("@", 1)[0], "email_results": [], "breach_count": 0, "source_errors": [], "logs": [], "created": time.time(), "updated": time.time()}
    threading.Thread(target=run_email_scan, args=(job_id, email), daemon=True).start()
    return jsonify({"job_id": job_id}), 202


@app.get("/api/search/<job_id>")
def search_status(job_id: str):
    cleanup_jobs()
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Search not found or expired."}), 404
        safe_job = {key: value for key, value in job.items() if key not in {"created", "updated", "command"}}
    return jsonify(safe_job)


@app.get("/healthz")
def healthz():
    try:
        import sherlock_project  # noqa: F401
        sherlock_ok = True
    except Exception:
        sherlock_ok = False
    try:
        import socialscan  # noqa: F401
        socialscan_ok = True
    except Exception:
        socialscan_ok = False
    return jsonify({"ok": True, "sherlock": sherlock_ok, "socialscan": socialscan_ok, "xposedornot": True, "hibp_configured": bool(HIBP_API_KEY)})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
