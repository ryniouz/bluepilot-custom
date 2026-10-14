"""BluePilot data export bridge (Custom).

A small authenticated HTTP API that lets a home server (the Citadel comma app)
pull finished drives, follow live state and mark segments as synced, so the
deleter can keep unsynced drives until they are safely copied off the device.
Spec: DEVICE-API.md (api version 1).
"""

API_VERSION = 1
