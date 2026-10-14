# Comma device export API (bp_bridge) v1

Runs on the comma 3X as BluePilot process `bp_bridge` (source `bluepilot/bridge/` on branch `comma-export` of ryniouz/bluepilot-custom). The Citadel `comma` app is its only intended client.

## Transport and auth
- HTTP on port `BPBridgePort` (default **8090**), all interfaces.
- Every route except `GET /v1/ping` needs `Authorization: Bearer <BPBridgeToken>`. The token is generated on first start (32 random bytes, base64url) and shown in Settings > BluePilot > Data export; it can also be read once over SSH from `/data/params/d/BPBridgeToken`. Wrong or missing token: 401 `{error:"unauthorized"}`.
- Enabled by `BPBridgeEnabled` (default 0). Runs onroad and offroad. Process is niced (+10) and does no log decoding.
- JSON everywhere except file and snapshot bodies. Times are UTC ISO-8601 with ms. Units: m/s, m, °C, %, V, A, kW. Unknown values are `null`.

## Routes

### `GET /v1/ping` (no auth)
`{ "ok": true, "api": 1 }`

### `GET /v1/health`
```json
{ "ok": true, "api": 1, "version": "6.0.0-lc.1", "dongleId": "adef9b599f7b79ba", "onroad": false,
  "uptimeS": 1234, "freeSpacePct": 22.5, "keepUntilSynced": true, "unsyncedSegments": 41, "now": "2026-10-14T15:41:50.000Z" }
```

### `GET /v1/live`
Latest snapshot. Offroad: `device`, `onroad:false`, and `ev` while the car still publishes battery data (from `chargingStateBP` when the build has it, else a fresh `carStateBP`); everything else null. When the build has stream B's `charging` struct, `ev` also carries `charging` (bool), `chargeMode` (`ac`/`dc`/`other`/null), `chargeState` (e.g. `charging`, `targetReached`, `evsePaused`, `fault`), `chargePowerKw` (≥ 0 into the pack, null when unknown), `timeToFullH`, and offroad `sleepInS` (seconds until the comma sleeps). Fields are absent on builds without it.
```json
{ "t": "...", "onroad": true, "route": "00000123--a1b2c3d4e5", "segment": 7,
  "gps": { "lat": 49.28, "lon": -123.12, "alt": 54.1, "speed": 12.3, "bearing": 181.0, "acc": 3.0, "fix": true, "t": "..." },
  "car": { "speed": 12.1, "aEgo": 0.2, "gear": "drive", "steeringDeg": -3.5, "brake": false, "gasPressed": false,
           "leftBlinker": false, "rightBlinker": false, "standstill": false,
           "cruise": { "enabled": true, "speed": 27.8 } },
  "ev": { "available": true, "socPct": 81.5, "packV": 384.0, "packA": 31.5, "powerKw": 12.1, "rangeKm": 301.0, "packTempC": 24.5, "coolantTempC": 21.0 },
  "engaged": true, "latActive": true, "experimental": false,
  "device": { "cpuTempC": 61.0, "freeSpacePct": 22.5, "network": "wifi", "memPct": 48.0 } }
```
`car.speed`, `gps.speed`, `cruise.speed` are m/s. `ev` comes from `carStateBP.evBattery` (Lightning, ungated) when present, adding `rangeKm`, `packTempC`, `coolantTempC`; otherwise from `hybridBattery` with `powerKw` = V×A/1000. `powerKw` positive = drawing from the pack (driving), negative = charging/regen.

### `GET /v1/live/stream?hz=1`
Server-Sent Events. `event: live` with the `/v1/live` JSON, at `hz` (0.2..5, default 1). `event: drive` with each new event from `/v1/events`. Comment line `: ping` every 15 s.

### `GET /v1/events?since=<seq>&limit=100`
```json
{ "events": [ { "seq": 42, "t": "...", "kind": "drive_started|segment_closed|drive_finished|bookmark", "route": "00000123--a1b2c3d4e5", "segment": 7 } ], "next": 43 }
```
Persisted ring buffer (last 2000) in `/data/bluepilot/bridge/events.jsonl`; `seq` keeps increasing across restarts. `drive_finished` fires on the onroad→offroad edge; `segment_closed` when a segment directory loses its `.lock`; `bookmark` for each `userBookmark` message.

### `GET /v1/routes?synced=false`
```json
{ "routes": [ { "route": "00000123--a1b2c3d4e5", "firstSegmentAt": "...", "segments": [
  { "n": 0, "dir": "00000123--a1b2c3d4e5--0", "locked": false, "mtime": "...", "synced": false,
    "files": [ { "name": "rlog.zst", "size": 7340032 }, { "name": "qcamera.ts", "size": 3200000 } ] } ] } ] }
```
Route ids are the segment dir name without `--<n>`. `synced` filter: only routes with at least one unsynced (false) or all synced (true) segment. `firstSegmentAt` is the dir mtime of segment 0 (wall clock unreliable before GPS fix; Citadel anchors time on GPS in the log).

### `GET /v1/files/<segmentDir>/<file>`
Streams the file with `Range` support (206), `Content-Length`, `ETag` = `size-mtime`. Allowed names: `rlog.zst`, `qlog.zst`, `rlog`, `qlog`, `qcamera.ts`, `fcamera.hevc`, `ecamera.hevc`, `dcamera.hevc`. Path traversal refused (400). A segment still `locked` returns 409 unless `?allowLocked=1`.

### `POST /v1/synced`
Body `{ "segments": ["00000123--a1b2c3d4e5--0", ...], "level": "logs|full" }`. Marks segments synced (`logs` = rlog+qcamera pulled; `full` = all cameras). Returns `{ "marked": n }`. Stored in `/data/bluepilot/bridge/synced.json`.

### `GET /v1/snapshot?camera=road`
Latest `thumbnail` JPEG from the road camera (onroad only, ~1/min upstream rate). 404 when none. (Full-res stills come from video files.)

### `GET /v1/params?keys=a,b` and `PUT /v1/params/<key>`
Read any key in the allowlist, returned as `{ "params": { key: value }, "writable": [keys] }`; write `{ "value": ... }` only when **offroad** (`IsOnroad` false), else 409 `{error:"onroad"}`. Allowlist = BluePilot/sunnypilot display and tuning keys (see `bluepilot/bridge/params_allowlist.py`). Never writes safety or calibration keys.

### `GET /v1/settings` and `PUT /v1/settings` (remote settings, like sunnypilot connect)
`GET` returns `{ onroad, editable, groups: [{ id, title, settings: [{ key, type: "bool|choice|int|float", title, description, options?: [{value,label}], min?, max?, step?, unit?, value }] }] }`. Groups: driving, speed_limit, lateral, longitudinal, display, device (metadata in `bluepilot/bridge/settings_schema.py`).
`PUT` body `{ "values": { key: value, ... } }` validates every value against its metadata first, then writes them all; returns `{ applied: { key: value } }`. 409 `onroad` while driving, 403 for keys outside the schema, 400 for out-of-range or invalid choices (nothing is written). The device's own settings screens read the same params, so both stay in sync.

## Keep-until-synced
With `BPKeepUntilSynced` = 1 (default 1 when bridge enabled), `system/loggerd/deleter.py` deletes synced segments first (oldest first). It only deletes unsynced segments when free space falls below the hard floor (5% or 2 GB), so the comma never fills up.

## Drive-finished push (optional)
If `BPBridgeNotifyUrl` is set, on each `drive_finished` (and on reconnect if there are unsynced segments) the bridge POSTs `{event}` JSON to that URL with `Authorization: Bearer <BPBridgeToken>`, 5 s timeout, best effort, no retries beyond the next event. The Citadel comma app has a LAN address (Citadel `lan` network) and exposes this as `POST /device/v1/notify`, checking the same token.
