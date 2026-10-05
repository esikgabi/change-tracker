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
NONCE = re.compile(r"([?&])_wpnonce=[^&#]*&?")


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
    links = sorted({NONCE.sub(r"\1", a["href"]).rstrip("?&") for a in root.find_all("a", href=True)})
    return text, links


def signature(text, links):
    return hashlib.sha256((text + "\n--\n" + "\n".join(links)).encode()).hexdigest()


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


def fetch(url):
    headers = {"User-Agent": "change-tracker/1.0"}
    for attempt in (1, 2):
        try:
            r = requests.get(url, timeout=30, headers=headers)
            r.raise_for_status()
            return r.content
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
        text, links = normalize(fetch_fn(cfg.url), cfg.selector)
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
        st["failures"] = 0
        _save(cfg.state_path, st)
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
