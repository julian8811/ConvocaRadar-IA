# ConvocaRadar daily status maintenance

This operational fallback needs no application redeployment or worker restart. It runs one daily PostgreSQL transaction to set `status=closed` only for rows marked `open`/`closing_soon` with stored deadline before today's UTC date.

**Important**: Stored dates do not prove no official extension was issued. The team should audit documents and any revised deadlines. Do not also enable a similar in-worker job until this systemd timer is removed.

## Install (without activation)

```sh
sudo install -m 0750 convocaradar-reconcile-expired.sh /usr/local/sbin/convocaradar-reconcile-expired.sh
sudo install -m 0644 convocaradar-status-reconcile.service /etc/systemd/system/
sudo install -m 0644 convocaradar-status-reconcile.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo /usr/local/sbin/convocaradar-reconcile-expired.sh preview
systemd-analyze calendar '*-*-* 13:15:00 UTC'
```

## Activate after checking backup and preview

```sh
sudo systemctl enable --now convocaradar-status-reconcile.timer
sudo systemctl list-timers --all | grep convocaradar-status
sudo journalctl -u convocaradar-status-reconcile.service -n 60 --no-pager
```

## Rollback

```sh
sudo systemctl disable --now convocaradar-status-reconcile.timer
```

Notes: `Persistent=true` may trigger immediate catch-up after enablement if an execution was missed. Do not activate without reviewing. The hard limit is 500 changes per run; more aborts. PostgreSQL `ROLLBACK` on error, timeout guard, `flock` to prevent concurrent maintenance. Logs are in `journalctl`. Backup integrity still requires a restoration test.
