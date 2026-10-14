# Data export bridge (Custom)

`bp_bridge` lets a home server pull drives off the comma 3X and follow live state, without SSH. The Citadel `comma` app is its client. The API contract is [DEVICE-API.md](DEVICE-API.md).

- Turn on with the `BPBridgeEnabled` param. Port `BPBridgePort` (8090). A bearer token is generated into `BPBridgeToken` on first start.
- Read-only for drives and video. Settings writes are limited to an allowlist and refused while driving.
- `BPKeepUntilSynced` (default on): the deleter removes synced segments first and only removes unsynced ones below 5% / 2 GB free.
- `BPBridgeNotifyUrl`: optional URL that receives `drive_finished` events so the home server pulls straight away.
- The process is niced and does no log decoding; decoding happens on the server.

Tests run off-device (no build needed):

```
cd bluepilot/bridge
PYTHONPATH=<dir with openpilot -> repo symlink>:<repo> pytest --rootdir=. --confcutdir=. tests -o addopts=""
```
