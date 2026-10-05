# Change Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Dockerized Python watcher that polls one WordPress page and emails on visible text/link changes.

**Architecture:** Single file `watcher.py` with small functions (`normalize`, `signature`, `build_body`, `fetch`, `send_mail`, `check`, `main`). `check` takes injectable `fetch_fn`/`send` so tests need no network or SMTP. Scheduling is a sleep loop in `main` (see spec, "Scheduling"). State is a JSON file in `/data`.

**Tech Stack:** Python 3.12, requests, beautifulsoup4, stdlib (smtplib, difflib, hashlib, json). Docker / compose on ARM64.

Spec: `docs/superpowers/specs/2026-10-05-change-tracker-design.md`

## File Structure
- Create: `watcher.py` - all logic
- Create: `test_watcher.py` - plain-assert tests, run with `python test_watcher.py`
- Create: `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.gitignore`
- Modify: `README.md` - setup/usage

---

### Task 1: Project skeleton and normalize()

**Files:** Create `requirements.txt`, `.gitignore`, `watcher.py`, `test_watcher.py`

- [ ] **Step 1: Create skeleton files**

`requirements.txt`:
```
requests==2.32.3
beautifulsoup4==4.12.3
```
`.gitignore`:
```
data/
__pycache__/
.venv/
.env
```
Then: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`

- [ ] **Step 2: Write the failing test** - `test_watcher.py`

```python
import json, os, tempfile
from types import SimpleNamespace

import watcher

PAGE = """<html><head><script>var n="{nonce}";</script></head><body>
<!-- generated {nonce} -->
<input type="hidden" name="_wpnonce" value="{nonce}">
<h1>Event</h1><p>Registration opens soon</p>
<a href="/about?_wpnonce={nonce}">About</a>
{extra}
</body></html>"""


def page(nonce="aaa", extra=""):
    return PAGE.format(nonce=nonce, extra=extra)


def test_normalize_ignores_noise():
    assert watcher.normalize(page("aaa")) == watcher.normalize(page("bbb"))


def test_normalize_detects_new_link_and_text():
    base = watcher.normalize(page())
    new = watcher.normalize(page(extra='<a href="/register">Register now</a>'))
    assert watcher.signature(*base) != watcher.signature(*new)
    assert "/register" in new[1]
    assert "Register now" in new[0]


def test_normalize_selector():
    html = '<div id="a">one</div><div id="b">two</div>'
    assert watcher.normalize(html, "#a")[0] == "one"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/bin/python test_watcher.py`
Expected: FAIL `ModuleNotFoundError: No module named 'watcher'`

- [ ] **Step 4: Implement** - `watcher.py`

```python
import difflib
import hashlib
import json
import logging
import os
import re
import smtplib
import time
from dataclasses import dataclass
from email.message import EmailMessage

import requests
from bs4 import BeautifulSoup, Comment

log = logging.getLogger("watcher")
NONCE = re.compile(r"[?&]_wpnonce=[^&#]*")


def normalize(html, selector=None):
    """Return (visible_text, sorted_links), ignoring scripts/comments/hidden inputs/nonces."""
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(selector) if selector else soup
    if root is None:
        raise ValueError(f"selector {selector!r} matched nothing")
    for c in root.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    for t in root.find_all(["script", "style", "noscript"]):
        t.decompose()
    for t in root.find_all("input", type="hidden"):
        t.decompose()
    lines = (ln.strip() for ln in root.get_text("\n").splitlines())
    text = "\n".join(ln for ln in lines if ln)
    links = sorted({NONCE.sub("", a["href"]) for a in root.find_all("a", href=True)})
    return text, links


def signature(text, links):
    return hashlib.sha256((text + "\n--\n" + "\n".join(links)).encode()).hexdigest()
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/bin/python test_watcher.py`
Expected: three `ok` lines

- [ ] **Step 6: Commit**

```bash
git add requirements.txt .gitignore watcher.py test_watcher.py
git commit -m "feat: normalize page into visible text and links"
```

---

### Task 2: Email body and SMTP sender

**Files:** Modify `watcher.py`, `test_watcher.py`

- [ ] **Step 1: Add failing test** (insert before the `if __name__` block)

```python
def test_build_body():
    body = watcher.build_body("http://x/e", "a\nb", "a\nc", ["/a"], ["/a", "/register"])
    assert "http://x/e" in body
    assert "-b" in body and "+c" in body
    assert "/register" in body and "New links" in body
```

- [ ] **Step 2: Run** - Expected: FAIL `AttributeError: ... 'build_body'`

- [ ] **Step 3: Implement** (append to `watcher.py`)

```python
@dataclass
class Config:
    url: str
    smtp_host: str
    smtp_user: str
    smtp_pass: str
    mail_to: str
    smtp_port: int = 587
    interval_min: int = 15
    selector: str = None
    state_path: str = "/data/state.json"

    @classmethod
    def from_env(cls):
        e = os.environ
        return cls(
            url=e["WATCH_URL"], smtp_host=e["SMTP_HOST"], smtp_user=e["SMTP_USER"],
            smtp_pass=e["SMTP_PASS"], mail_to=e["MAIL_TO"],
            smtp_port=int(e.get("SMTP_PORT", 587)),
            interval_min=int(e.get("INTERVAL_MIN", 15)),
            selector=e.get("CSS_SELECTOR") or None,
            state_path=e.get("STATE_PATH", "/data/state.json"),
        )


def build_body(url, old_text, new_text, old_links, new_links):
    diff = "\n".join(difflib.unified_diff(
        old_text.splitlines(), new_text.splitlines(), "before", "after", lineterm="", n=1))
    added = sorted(set(new_links) - set(old_links))
    links = "\n".join(added) or "(none)"
    return f"Page changed: {url}\n\nNew links:\n{links}\n\nText diff:\n{diff or '(links only)'}\n"


def send_mail(cfg, subject, body):
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, cfg.smtp_user, cfg.mail_to
    msg.set_content(body)
    if cfg.smtp_port == 465:
        s = smtplib.SMTP_SSL(cfg.smtp_host, 465, timeout=30)
    else:
        s = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30)
        s.starttls()
    with s:
        s.login(cfg.smtp_user, cfg.smtp_pass)
        s.send_message(msg)
```

- [ ] **Step 4: Run** - Expected: four `ok` lines

- [ ] **Step 5: Commit**

```bash
git add watcher.py test_watcher.py
git commit -m "feat: config, email body and SMTP sender"
```

---

### Task 3: check() logic with state and failure alerts

**Files:** Modify `watcher.py`, `test_watcher.py`

- [ ] **Step 1: Add failing tests** (before `if __name__`)

```python
def make_cfg():
    d = tempfile.mkdtemp()
    return SimpleNamespace(url="http://x", selector=None, state_path=os.path.join(d, "s.json"))


def run(cfg, html=None, boom=False, send_fails=False):
    sent = []

    def fetch_fn(url):
        if boom:
            raise RuntimeError("down")
        return html

    def send(cfg_, subject, body):
        if send_fails:
            raise OSError("smtp down")
        sent.append(subject)

    try:
        watcher.check(cfg, fetch_fn, send)
    except OSError:
        pass
    return sent


def test_baseline_then_no_change_then_change():
    cfg = make_cfg()
    assert run(cfg, page("a")) == ["Watcher started"]
    assert run(cfg, page("b")) == []  # nonce noise only
    assert run(cfg, page(extra='<a href="/r">Register</a>')) == ["Page changed"]
    assert run(cfg, page(extra='<a href="/r">Register</a>')) == []


def test_smtp_failure_retries_change():
    cfg = make_cfg()
    run(cfg, page())
    assert run(cfg, page(extra="<p>new</p>"), send_fails=True) == []
    assert run(cfg, page(extra="<p>new</p>")) == ["Page changed"]


def test_failure_alert_once_then_recovery():
    cfg = make_cfg()
    run(cfg, page())
    assert run(cfg, boom=True) == []
    assert run(cfg, boom=True) == []
    assert run(cfg, boom=True) == ["Watcher failing"]
    assert run(cfg, boom=True) == []
    assert run(cfg, page()) == ["Watcher recovered"]
```

- [ ] **Step 2: Run** - Expected: FAIL `AttributeError: ... 'check'`

- [ ] **Step 3: Implement** (append to `watcher.py`)

```python
def fetch(url):
    headers = {"User-Agent": "change-tracker/1.0"}
    for attempt in (1, 2):
        try:
            r = requests.get(url, timeout=30, headers=headers)
            r.raise_for_status()
            return r.text
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(5)


def _load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _save(path, st):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, path)  # atomic


def check(cfg, fetch_fn=fetch, send=send_mail):
    """One poll. Mail is sent BEFORE state is saved, so an SMTP failure retries next cycle."""
    st = _load(cfg.state_path)
    fails = st.get("failures", 0)
    try:
        html = fetch_fn(cfg.url)
    except Exception as e:
        log.warning("fetch failed: %s", e)
        fails += 1
        if fails == 3:
            send(cfg, "Watcher failing", f"3 consecutive fetch failures for {cfg.url}: {e}")
        st["failures"] = fails
        _save(cfg.state_path, st)
        return
    if fails >= 3:
        send(cfg, "Watcher recovered", f"Fetching {cfg.url} works again.")
    text, links = normalize(html, cfg.selector)
    h = signature(text, links)
    if "hash" not in st:
        send(cfg, "Watcher started", f"Baseline stored for {cfg.url}")
    elif h != st["hash"]:
        send(cfg, "Page changed", build_body(cfg.url, st["text"], text, st["links"], links))
    st.update(hash=h, text=text, links=links, failures=0)
    _save(cfg.state_path, st)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config.from_env()
    while True:
        try:
            check(cfg)
        except Exception:
            log.exception("check failed")
        time.sleep(cfg.interval_min * 60)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run** - Expected: seven `ok` lines

- [ ] **Step 5: Commit**

```bash
git add watcher.py test_watcher.py
git commit -m "feat: check loop with baseline, change and failure alerts"
```

---

### Task 4: Docker packaging and README

**Files:** Create `Dockerfile`, `docker-compose.yml`, `.dockerignore`; Modify `README.md`

- [ ] **Step 1: `Dockerfile`**

```dockerfile
FROM python:3.12-alpine
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY watcher.py .
RUN adduser -D app && mkdir /data && chown app /data
USER app
ENV PYTHONUNBUFFERED=1
CMD ["python", "watcher.py"]
```

- [ ] **Step 2: `docker-compose.yml`**

```yaml
services:
  change-tracker:
    build: .
    restart: unless-stopped
    environment:
      WATCH_URL: "https://example.com/event"
      INTERVAL_MIN: "15"
      SMTP_HOST: "smtp.gmail.com"
      SMTP_PORT: "587"
      SMTP_USER: "you@gmail.com"
      SMTP_PASS: "app-password"
      MAIL_TO: "you@gmail.com"
      # CSS_SELECTOR: "main"
    volumes:
      - ./data:/data
```

- [ ] **Step 3: `.dockerignore`**

```
.git
.venv
data
docs
test_watcher.py
```

- [ ] **Step 4: Replace `README.md`** with: one-paragraph purpose; "Run: edit env vars in `docker-compose.yml`, then `docker compose up -d --build`"; "Logs: `docker compose logs -f`"; "Test: `python test_watcher.py`"; note that the first start sends a "Watcher started" email (SMTP check), and that Gmail needs an app password; tip to lower `INTERVAL_MIN` near registration opening.

- [ ] **Step 5: Verify build and live SMTP/fetch**

Run: `docker compose build` (on the Pi, or anywhere with Docker)
Expected: build succeeds.
Then set real values and run `docker compose up -d`; `docker compose logs` has no errors and the "Watcher started" email arrives. Edit `./data/state.json` (change `hash`) and restart; a "Page changed" email must arrive.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile docker-compose.yml .dockerignore README.md
git commit -m "feat: Docker packaging and README"
```

---

## Self-Review
- Spec coverage: fetch+retry (T3), normalize/selector/nonce noise (T1), email diff+new links (T2), state file (T3), config env vars (T2), scheduling loop with exception guard (T3 `main`), baseline/started email, SMTP-failure retry, 3-failure alert + recovery (T3), Docker/compose/non-root/restart (T4), tests (T1-3). No gaps.
- Consistency: `normalize`->`(text, links)`, `signature(text, links)`, `build_body(url, old_text, new_text, old_links, new_links)`, `check(cfg, fetch_fn, send)`, state keys `hash/text/links/failures` used consistently.
- Known limits: a persistent selector mismatch raises each cycle (logged, no email); state stores full page text (small).
