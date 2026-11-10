# WoW Forever character snapshot on Worldnode

The read-only Blizzard character collector uses `scripts/collect_wow_forever.py` and is **separate from the standard observer pipeline and Git history**. It publishes one short-lived JSON snapshot to the website at `/world-observer/data/wow-forever-dennis-hilk.json`, not a history.

## Before installing

- `/home/nebu/.config/wow-forever-observer/credentials` exists with exactly two lines: Blizzard client ID and Blizzard client secret, in that order. Directory mode 0700 and file mode 0600.
- `/srv/www/dennishilk.github.io/world-observer/data` exists.
- The website Git checkout's local `.git/info/exclude` contains `/world-observer/data/`, to keep published snapshots out of commits.
- The collector has passed `python3 -m unittest discover -s tests -p 'test_wow_forever_collector.py' -v` and `python3 scripts/collect_wow_forever.py --dry-run`.

## Install and enable on Worldnode

The two systemd units are versioned in `systemd/`. Install them to `/etc/systemd/system/` with root privileges, then reload and enable the timer:

```sh
sudo install -m 644 systemd/world-observer-wow-forever.service /etc/systemd/system/world-observer-wow-forever.service
sudo install -m 644 systemd/world-observer-wow-forever.timer /etc/systemd/system/world-observer-wow-forever.timer
sudo systemctl daemon-reload
sudo systemctl enable --now world-observer-wow-forever.timer
```

Optionally trigger a single run and verify status:

```sh
sudo systemctl start world-observer-wow-forever.service
systemctl status world-observer-wow-forever.service --no-pager
systemctl list-timers --all --no-pager | grep world-observer-wow-forever
```

The timer is hourly, with up to five minutes of randomized delay to avoid hitting the API at the exact top of the hour. A failed API request does not replace the last successful snapshot; the JSON contains an `expires_at` timestamp and the frontend rejects expired data. No credentials or access tokens appear in the JSON, script output, Git, or journal.

Security note: the service runs as `nebu` with read-only system/home mounts and a single writable directory for public snapshots. Never paste the credentials file into logs or issue trackers. Respect Blizzard's Developer API Terms and remove character data when access is revoked.
