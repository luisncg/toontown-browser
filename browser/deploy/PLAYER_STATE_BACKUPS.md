# Player-state backups

Production player state is backed up once per day to the private GitHub
repository `luisncg/toontown-player-state-backups`. Every snapshot is encrypted
on `COV0936` before it leaves the server. The dedicated server has only:

- the public age recipient, which can encrypt but cannot decrypt;
- a repository-scoped GitHub deploy key that can access only the private
  backup repository.

The age decryption identity is stored off-host at
`/Users/luiscg/.ssh/toontown-player-state-backup-age.key`. Never copy it to the
dedicated server, the application repository, R2, browser code, or logs.

## Consistency and availability

The root-owned backup service freezes the `toontown-browser.service` cgroup,
archives `astron/databases` and `data`, and immediately thaws the cgroup before
compression/encryption/upload work. This preserves one consistent filesystem
point without logging players out. Cleanup traps always attempt a thaw.

Snapshots and their small non-sensitive manifests are retained indefinitely.
This policy deliberately performs no automated deletion of recovery data.

## Monitoring

`toontown-player-state-backup-health.timer` checks every six hours that:

- a successful backup exists and is no more than 36 hours old;
- the Toontown Browser service is active.

Inspect failures with:

```bash
sudo systemctl status toontown-player-state-backup.service
sudo systemctl status toontown-player-state-backup-health.service
sudo journalctl -u toontown-player-state-backup.service -n 100 --no-pager
```

## Non-destructive restore drill

Run from the development Mac:

```bash
./browser/scripts/restore-player-state-backup-drill.sh
```

The drill clones the private backup repository into a temporary directory,
decrypts its latest snapshot off-host, verifies its SHA-256 and safe archive
paths, extracts it only into that temporary directory, and then removes the
temporary files. It never writes to production.

Restoring into production is a separate, destructive operational decision. Do
not overwrite live Astron or application data without a current inventory,
backup, rollback plan, and the owner's new explicit approval.
