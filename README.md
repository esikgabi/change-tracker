# change-tracker

Polls one WordPress page and emails you when its visible text or links change.

## Run
Edit the env vars in `docker-compose.yml`, then:

    docker compose up -d --build

Logs: `docker compose logs -f`

Test: `python test_watcher.py`

## Notes
- The first start sends a "Watcher started" email (doubles as an SMTP check).
- Gmail requires an app password (not your account password).
- Lower `INTERVAL_MIN` near registration opening.
