# Change Tracker - Design

## Problem
Watch one WordPress page (event registration link, 30 seats) and email on change. Runs in one Docker container on Raspberry Pi 5 (ARM64, OpenMediaVault).

## Decisions
- Language: Python 3.12 (`requests`, `beautifulsoup4`; stdlib `smtplib`, `difflib`, `hashlib`, `json`).
- Page is server-rendered WordPress: plain HTTP GET, no headless browser.
- Change = visible text or links changed (scripts, styles, noscript, comments, hidden inputs ignored).
- Email via existing SMTP account (env vars).
- Interval: 15 min default (`INTERVAL_MIN`).
- Alternatives rejected: Go binary (more code, little gain), changedetection.io (too heavy).

## Architecture
One container, one process, one file `watcher.py`, sleep loop. No cron, scheduler lib or database.

```
loop every INTERVAL_MIN:
  fetch(url) -> normalize(html) -> compare with /data/state.json
    changed -> send email to all recipients (diff + new links + URL) -> save state
    fetch failed 3x in a row -> one "watcher failing" email (admin only)
    recovered -> one "recovered" email (admin only)
```

## Components
- `fetch`: requests.get, 30 s timeout, custom User-Agent, one retry.
- `normalize`: BeautifulSoup strips script/style/noscript/comments/hidden inputs (optionally narrowed by `CSS_SELECTOR`); outputs visible text lines + sorted hrefs. SHA-256 of that is the change signal.
- `notify`: smtplib (STARTTLS on 587 or SSL on 465). Body: unified diff of text, newly added links, URL.
- State: `/data/state.json` (hash, text, links, consecutive failure count) on a mounted volume.

## Scheduling
No cron. `watcher.py` is the container's main process and loops:

```python
while True:
    try: check()
    except Exception: log.exception("check failed")
    time.sleep(INTERVAL_MIN * 60)
```

- Docker runs the container; `restart: unless-stopped` restarts it after a crash or a Pi/Docker reboot (OMV starts Docker on boot).
- An exception in one cycle is logged and the loop continues.
- Interval is "INTERVAL_MIN after the previous check finished", not clock-aligned; drift is irrelevant here.
- Rejected: in-container cron (extra daemon, env passing), host cron with `docker run` (cold start per check).

## Config (env vars)
`WATCH_URL`, `INTERVAL_MIN=15`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `MAIL_TO` (comma/semicolon separated list; first = admin gets all mails, the rest get only "Page changed"), optional `CSS_SELECTOR`.

## Deployment
`python:3.12-alpine`, non-root user, `restart: unless-stopped`, `docker-compose.yml` mounting `./data:/data` (pasteable into OMV Compose plugin). Builds natively on ARM64.

## Error handling
- First run: store baseline, no change alert; send a "watcher started" email to the admin (SMTP test).
- SMTP failure: state is NOT updated, so the change is retried next cycle.
- Fetch failure (network/5xx): log, retry next cycle; alert after 3 consecutive failures, once.

## Testing
`test_watcher.py`, plain asserts: normalize ignores nonce/script changes but detects a new link; diff/email body built correctly; SMTP faked.

## Out of scope
Web UI, multiple URLs, database, headless browser.

## Note
A 15 min interval may be too slow for a 30-seat race; lower `INTERVAL_MIN` near opening time.
