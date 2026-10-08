# change-tracker

Single-file Python 3.12 watcher (`watcher.py`) that polls one URL and emails on text/link changes. Deployed via Docker (`docker-compose.yml`, or `docker-compose.omv.yml` for OpenMediaVault, config via `.env.example`).

- Test: `python test_watcher.py` (plain script, no pytest config; uses `.venv` if present). Tests inject `fetch_fn`/`send` fakes, so no network/SMTP needed.
- Deps are pinned in `requirements.txt`; the Dockerfile copies only `watcher.py`, so any new module must be added to the Dockerfile `COPY`.
- Runs as non-root user `app`; state lives in `state.json` under `/data` (mounted from `DATA_DIR`, must be writable by PUID:PGID).
- Normalization must strip volatile noise (nonces, comments, scripts); keep `test_normalize_ignores_noise` passing when changing `normalize`.
- First start intentionally sends a "Watcher started" email (SMTP check).
- `MAIL_TO` is a list: first = admin (all mails), rest = "Page changed" only (`send(..., everyone=True)`). Any new mail type must choose `everyone` deliberately.
