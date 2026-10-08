# Multiple recipients Implementation Plan

**Goal:** `MAIL_TO` accepts several addresses. The first is the admin and gets every mail type. The others are simple users and get only "Page changed".

**Design decisions**
- Format: `MAIL_TO="admin@x.com, mum@y.com; dad@z.com"`, separated by `,` or `;`. Order sets the role. No new env var, and the compose files and `.env.example` keys are unchanged.
- Recipients may see each other (family app), so a plain `To` header is used. No Bcc.
- Admin mails: "Watcher started", "Watcher failing", "Watcher recovered", "Page changed". User mails: "Page changed" only.
- A single address behaves exactly as it does today.

**Files:** modify `watcher.py`, `test_watcher.py`, `.env.example`, `README.md`, `AGENTS.md`.

---

## Task 1: Recipient parsing and selection (TDD)

- [ ] **Step 1: Write failing tests** in `test_watcher.py` (before the `__main__` block):

```python
def test_parse_recipients():
    assert watcher.parse_recipients("a@x, b@y;") == ["a@x", "b@y"]
    assert watcher.parse_recipients("a@x") == ["a@x"]
    try:
        watcher.parse_recipients(" ,; ")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_recipient_roles():
    cfg = SimpleNamespace(mail_to=["admin@x", "u1@y", "u2@z"])
    assert watcher.recipients(cfg, everyone=False) == ["admin@x"]
    assert watcher.recipients(cfg, everyone=True) == ["admin@x", "u1@y", "u2@z"]
```

- [ ] **Step 2: Run** `python test_watcher.py`. Expect `AttributeError: module 'watcher' has no attribute 'parse_recipients'`.

- [ ] **Step 3: Implement** in `watcher.py`, above `Config`:

```python
def parse_recipients(s):
    """First address = admin (all mails); the rest get 'Page changed' only."""
    out = [a.strip() for a in re.split(r"[;,]", s) if a.strip()]
    if not out:
        raise ValueError("MAIL_TO has no addresses")
    return out


def recipients(cfg, everyone):
    return cfg.mail_to if everyone else cfg.mail_to[:1]
```

- [ ] **Step 4: Run** `python test_watcher.py`. The two new tests print `ok`.

## Task 2: Wire into config, sending and check

- [ ] **Step 1: Update the fakes and add a failing role test** in `test_watcher.py`:
  - In `run`, change `send` to `def send(cfg_, subject, body, everyone=False)` and record `sent.append((subject, everyone))`. In `test_recovered_sent_once_even_if_next_send_fails`, give its `send` the same `everyone=False` parameter.
  - Add a helper `subjects(sent)` returning `[s for s, _ in sent]`.
  - Update the existing assertions to compare `subjects(...)` instead of the raw list. Keep the lists they compare against unchanged.
  - Add:

```python
def test_only_page_changed_goes_to_everyone():
    cfg = make_cfg()
    assert run(cfg, page()) == [("Watcher started", False)]
    assert run(cfg, page(extra="<p>new</p>")) == [("Page changed", True)]
    for _ in range(3):
        sent = run(cfg, boom=True)
    assert sent == [("Watcher failing", False)]
    assert run(cfg, page(extra="<p>new</p>")) == [("Watcher recovered", False)]
```

  Note: the last call is a recovery, and the content differs from the stored baseline, so check also sends "Page changed" in the same cycle. The expected value is therefore `[("Watcher recovered", False), ("Page changed", True)]`. Write the assertion that way.

- [ ] **Step 2: Run.** Expect failures: `check` doesn't pass `everyone`, and `Config` doesn't parse yet.

- [ ] **Step 3: Implement** in `watcher.py`:
  - `Config.mail_to: list` and in `from_env`: `mail_to=parse_recipients(e["MAIL_TO"])`.
  - `send_mail(cfg, subject, body, everyone=False)`:
    - `msg["To"] = ", ".join(recipients(cfg, everyone))`
    - `refused = s.send_message(msg)`, then `if refused: log.warning("recipients refused: %s", refused)`. `smtplib` raises only when all recipients are refused.
  - In `check`, change only the "Page changed" call to `send(cfg, "Page changed", build_body(...), everyone=True)`. The other three calls are untouched.
  - Update `make_cfg` in the tests only if a test needs `mail_to`. The fakes ignore it.

- [ ] **Step 4: Run** `python test_watcher.py`. Every test prints `ok`, including `test_normalize_ignores_noise` and the pre-existing check tests.

## Task 3: Docs

- [ ] `.env.example`: replace the `MAIL_TO` line with
  `# First address = admin (all mails). Others get "Page changed" only. Separate with , or ;`
  followed by `MAIL_TO=you@gmail.com, family@example.com`.
- [ ] `README.md` Notes: add "`MAIL_TO` takes several addresses (`,` or `;`). The first is the admin and gets every mail; the rest get only 'Page changed'."
- [ ] `AGENTS.md`: add "`MAIL_TO` is a list: first = admin (all mails), rest = 'Page changed' only (`send(..., everyone=True)`). Any new mail type must choose `everyone` deliberately."

## Task 4: Verify and commit

- [ ] Run `python test_watcher.py` and confirm all `ok`.
- [ ] Optional manual SMTP check: set `MAIL_TO` to two addresses, start the watcher, and confirm only the admin gets "Watcher started".
- [ ] `git add watcher.py test_watcher.py .env.example README.md AGENTS.md docs/superpowers/plans/2026-10-08-multiple-recipients.md`
- [ ] `git commit -m "feat: multiple recipients, admin gets all mails, others page-change only"`

**Skipped:** per-user roles beyond first versus rest, Bcc, and a separate failure-alert list. Add them only if the family setup outgrows this.
