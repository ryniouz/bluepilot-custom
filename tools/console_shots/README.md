# console_shots: headless UI screenshots

`shoot.py` renders the TICI (BIG) raylib UI, including BluePilot's `AugmentedRoadViewBP`, sidebar, home and settings, to PNG files. It needs no device, camera or car.

- **Fresh imports.** Each scene runs in its own Python process and its own `OpenpilotPrefix` (a private params dir and msgq namespace). UI code is imported fresh on every run.
- **Fake messages.** Cereal messages are published with `PubMaster` every frame: deviceState, pandaStates, selfdriveState, carState, controlsState, radarState, modelV2, liveCalibration, carStateBP and others.
- **Synthetic road.** A road image (lanes, tree line and a lead car at the radar lead distance) is streamed over VisionIPC as the road camera, so the real camera shader and calibration path are used.
- **Capture.** The frame is read back from the app's render texture after `rl.end_drawing()`.

## Environment

| what | where |
|---|---|
| venv (Python 3.12, `uv sync --frozen` + `coverage`, `pillow`) | `/home/claude/bp-venv` |
| submodules initialised (`--depth 1`) | `msgq_repo`, `panda`, `rednose_repo`, `teleoprtc_repo` |
| baseline (clean HEAD) git worktree | `/home/claude/bp-baseline` |

To recreate the venv:

```bash
cd /home/claude/bluepilot-custom
git submodule update --init --depth 1 msgq_repo panda rednose_repo teleoprtc_repo
UV_PROJECT_ENVIRONMENT=/home/claude/bp-venv /root/.local/bin/uv sync --frozen --python 3.12
/root/.local/bin/uv pip install --python /home/claude/bp-venv/bin/python pillow coverage
```

## Build (targeted, takes about a minute)

```bash
cd /home/claude/bluepilot-custom && source /home/claude/bp-venv/bin/activate
scons -j8 common/params_pyx.so msgq_repo/msgq/ipc_pyx.so msgq_repo/msgq/visionipc/visionipc_pyx.so cereal selfdrive/assets/fonts
```

Rebuild in these cases:
- `common/params_keys.h` changed (new params need `params_pyx.so` to be rebuilt).
- Fonts were added under `selfdrive/assets/fonts`.
- `cereal/*.capnp` changed.

`shoot.py --build` runs the same command for you.

## Take screenshots

```bash
source /home/claude/bp-venv/bin/activate
python /home/claude/bluepilot-custom/tools/console_shots/shoot.py --out /tmp/shots              # all scenes
python /home/claude/bluepilot-custom/tools/console_shots/shoot.py --build --out /tmp/shots      # rebuild first
python /home/claude/bluepilot-custom/tools/console_shots/shoot.py --out /tmp/shots --scenes home,onroad_engaged,alert_full
python /home/claude/bluepilot-custom/tools/console_shots/shoot.py --list
# render a different checkout (e.g. the clean baseline worktree):
python /home/claude/bluepilot-custom/tools/console_shots/shoot.py --repo /home/claude/bp-baseline --out /tmp/base
```

- With no `$DISPLAY`, the script re-runs itself under `xvfb-run -a` automatically.
- A full run (17 scenes, 33 PNGs) takes about 75 s with the default `--jobs 4`.
- Per-scene logs go to `<out>/logs/<scene>.log`. When a scene fails, the end of its traceback is printed in the summary.

Options:
- `--frames N`: frames to settle before a capture. The default is 90, which is 1.5 s of simulated time; animation time is frame-based.
- `--jobs N`: number of scenes rendered in parallel.
- `--timeout S`: per-scene timeout in seconds.

## Scenes

| scene | output |
|---|---|
| `home` | offroad home |
| `home_alerts` | offroad alerts + update-available state |
| `settings` | settings, Device panel |
| `settings_panels` | `settings_<panel>.png` for every panel: device, network, sunnylink, toggles, software, models, steering, cruise, visuals, display, osm, trips, vehicle, firehose, developer, bluepilot, bp_portal |
| `sidebar` | onroad engaged + sidebar open |
| `onroad_engaged` | engaged, lead at 38 m, 65 mph, set 70 |
| `onroad_disengaged` | cruise available, not engaged |
| `onroad_override` | state=overriding, gas+steer pressed |
| `onroad_experimental` | experimental mode |
| `alert_small`, `alert_mid`, `alert_full_prompt`, `alert_full_critical` | onroad alerts |
| `onroad_ev` | `carStateBP.hybridBattery` (SOC 78 %, 372.5 V, -46 A) + `FordPrefHybridBatteryStatus=1` |
| `onroad_ev_powerflow` | battery + power-flow gauge |
| `onroad_all` | every optional element we could enable (see `ONROAD_ALL_PARAMS`), plus blinker, blindspot, road name, speed limit, dev UI, torque bar |
| `onroad_debug_panel` | BluePilot controls debug panel |

Aliases:
- `alert_full` = prompt + critical
- `alerts` = all four alert scenes
- `onroad` = engaged, disengaged, override and experimental

## Baseline

`baseline/` holds the BEFORE pictures. They were rendered from a clean `HEAD` (f29bcae) worktree at `/home/claude/bp-baseline`, before the console restyle. To regenerate them:

```bash
python tools/console_shots/shoot.py --repo /home/claude/bp-baseline --out /tmp/base && cp /tmp/base/*.png tools/console_shots/baseline/
```

## Notes

- The harness never modifies tracked files.
- It turns off two things for the duration of each scene:
  - The "Recent Changes" popup, by setting `BPLastSeenVersion` to `BPVERSION`.
  - The device interactive timeout, via `device.set_override_interactive_timeout`. Otherwise settings and sidebar would auto-close, or the screen would sleep, during slow llvmpipe rendering.
- Network errors in the logs are harmless. These include comma API 403s through the proxy and dbus/NetworkManager being missing.
- The settings nav column does not scroll to the selected panel. For later panels, such as BluePilot, the highlighted entry may be off-screen, but the panel content is correct.
- CI's own replay also works: `xvfb-run -a python selfdrive/ui/tests/diff/replay.py --big`, run with `PYTHONPATH=.`. It writes `selfdrive/ui/tests/diff/report/tizi_ui_replay.mp4`, which is gitignored. Its hard-coded clicks don't match the BluePilot layout, because a Recent Changes dialog covers the screen.
