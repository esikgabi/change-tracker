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
