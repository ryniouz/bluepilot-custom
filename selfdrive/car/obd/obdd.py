#!/usr/bin/env python3
"""
Custom: OBD adapter service (stream B).

Polls a read-only set of Ford enhanced PIDs through an ELM327-compatible adapter and publishes
obdStateBP at 1 Hz. The adapter plugs into the truck's OBD port on its own, so this never touches
the panda or the comma's CAN connection, and panda safety is unaffected. Only read services
(01, 09, 22) can be sent; see catalog.check_request().

To avoid keeping the truck's modules awake, it polls only while the truck is on (IsOnroad) or
charging (BPChargingActive), unless BPObdPollWhenOff is set.
"""
import math
import time
from dataclasses import dataclass

import cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.car.obd.catalog import Pid, load_catalog
from openpilot.selfdrive.car.obd.elm327 import Elm327, ElmError, Negative, NoData
from openpilot.selfdrive.car.obd.transports import TransportError, bluetooth_status, make_transport, usb_candidates

PARAM_REFRESH_S = 2.0
PUBLISH_PERIOD_S = 1.0
STEP_BUDGET_S = 0.8          # time spent on requests per published message
BACKOFF_S = (5., 10., 20., 40., 60.)
ASLEEP_AFTER_MISSES = 6      # consecutive NO DATA answers across requests before calling the truck asleep
ASLEEP_PROBE_S = 10.
UNSUPPORTED_RETRY_S = 600.
VALUE_STALE_S = 120.
TRANSPORTS = ("none", "bluetooth", "wifi", "usb", "simulated")


@dataclass
class Settings:
  enabled: bool = False
  transport: str = "wifi"
  address: str = ""
  poll_when_off: bool = False
  onroad: bool = False
  charging: bool = False

  @property
  def may_poll(self) -> bool:
    return self.onroad or self.charging or self.poll_when_off


def read_settings(params: Params) -> Settings:
  return Settings(
    enabled=params.get_bool("BPObdEnabled"),
    transport=(params.get("BPObdTransport", return_default=True) or "wifi").strip().lower(),
    address=(params.get("BPObdAddress") or "").strip(),
    poll_when_off=params.get_bool("BPObdPollWhenOff"),
    onroad=params.get_bool("IsOnroad"),
    charging=params.get_bool("BPChargingActive"),
  )


class ObdService:
  def __init__(self, params: Params, transport_factory=make_transport, catalog: list[Pid] | None = None, catalog_desc: str = ""):
    self.params = params
    self.transport_factory = transport_factory
    if catalog is None:
      catalog, catalog_desc = load_catalog()
    self.catalog, self.catalog_desc = catalog, catalog_desc
    self.settings = Settings()
    self.settings_key = None
    self.last_settings = -math.inf
    self.transport = None
    self.elm: Elm327 | None = None
    self.link, self.message = "off", "OBD link is off"
    self.next_attempt = 0.
    self.failures = 0
    self.misses = 0
    self.next_due = dict.fromkeys(range(len(self.catalog)), 0.0)
    self.unsupported_until: dict[int, float] = {}
    self.values: dict[str, tuple] = {}  # short -> (name, value, unit, t, header, request)
    self.last_response = -math.inf
    self.request_times: list[float] = []
    self.bt_ok, self.bt_msg = bluetooth_status()

  # *** link management ***
  def _close(self, link: str, message: str):
    if self.transport is not None:
      try:
        self.transport.close()
      except OSError:
        pass
    self.transport, self.elm = None, None
    self.link, self.message = link, message

  def _fail(self, now: float, message: str):
    self.failures += 1
    delay = BACKOFF_S[min(self.failures, len(BACKOFF_S)) - 1]
    self.next_attempt = now + delay
    self._close("error", f"{message}; retrying in {int(delay)} s")
    cloudlog.warning(f"obdd: {message}")

  def _connect(self, now: float):
    s = self.settings
    self.link, self.message = "connecting", f"Connecting over {s.transport}"
    try:
      self.transport = self.transport_factory(s.transport, s.address)
      self.transport.open()
      self.link, self.message = "initializing", "Adapter found, setting it up"
      self.elm = Elm327(self.transport)
      self.elm.initialize()
    except (TransportError, ElmError, OSError) as e:
      self._fail(now, str(e))
      return
    self.failures, self.misses = 0, 0
    self.link, self.message = "connected", f"{self.elm.version or 'Adapter'} connected, waiting for the truck"

  def _update_settings(self, now: float):
    if now - self.last_settings < PARAM_REFRESH_S:
      return
    self.last_settings = now
    self.settings = read_settings(self.params)
    key = (self.settings.enabled, self.settings.transport, self.settings.address)
    if key != self.settings_key:  # reconnect with the new choice right away
      self.settings_key = key
      self._close("off", "OBD link is off")
      self.next_attempt, self.failures = now, 0

  # *** polling ***
  def _due_pid(self, now: float) -> int | None:
    best, best_t = None, math.inf
    for i, t in self.next_due.items():
      if self.unsupported_until.get(i, 0.) > now:
        continue
      if t <= now and t < best_t:
        best, best_t = i, t
    return best

  def _store(self, pid: Pid, data: bytes, now: float):
    for short, name, unit, fn in [(pid.short_name, pid.name, pid.unit, pid.decode)] + pid.extra:
      try:
        v = float(fn(data))
      except (ValueError, ZeroDivisionError, OverflowError, TypeError):
        continue
      if not math.isfinite(v) or (pid.min is not None and not (pid.min - 1e-6 <= v <= pid.max + 1e-6) and short == pid.short_name):
        continue
      self.values[short] = (name, v, unit, now, pid.header, pid.request)

  def _poll_one(self, now: float) -> bool:
    i = self._due_pid(now)
    if i is None:
      return False
    pid = self.catalog[i]
    asleep = self.link == "carAsleep"
    self.next_due[i] = now + (ASLEEP_PROBE_S if asleep else pid.period_s)
    self.request_times.append(now)
    try:
      data = self.elm.request(pid.header, pid.request)
    except NoData:
      self.misses += 1
      if self.misses >= ASLEEP_AFTER_MISSES:
        self.link, self.message = "carAsleep", "Adapter connected; the truck is not answering (asleep?)"
      return True
    except Negative as e:
      if e.nrc in (0x11, 0x12, 0x31):
        self.unsupported_until[i] = now + UNSUPPORTED_RETRY_S
      return True
    except ElmError:
      return True
    self.misses = 0
    self.last_response = now
    self.link, self.message = "connected", f"Reading {len(self.catalog)} values from the truck"
    self._store(pid, data, now)
    return True

  def step(self, now: float, clock=time.monotonic):
    self._update_settings(now)
    s = self.settings
    if not s.enabled:
      if self.link != "off":
        self._close("off", "OBD link is off")
    elif s.transport not in TRANSPORTS[1:]:
      self._close("unavailable", f"Unknown connection type {s.transport!r}")
    elif s.transport == "bluetooth" and not self.bt_ok:
      self._close("unavailable", f"Bluetooth is unavailable: {self.bt_msg}")
    elif not s.may_poll:
      if self.link not in ("idle", "off"):
        self._close("idle", "Paused while the truck is off and not charging")
      elif self.link == "off":
        self.link, self.message = "idle", "Waiting for the truck to turn on or charge"
    elif self.elm is None:
      if now >= self.next_attempt:
        self._connect(now)
    else:
      start = clock()
      try:
        while clock() - start < STEP_BUDGET_S and self._poll_one(now + (clock() - start)):
          pass
      except (TransportError, OSError) as e:
        self._fail(now, f"Adapter connection lost: {e}")
    return self.message_for(now)

  # *** output ***
  def message_for(self, now: float):
    dat = messaging.new_message("obdStateBP")
    dat.valid = True
    m = dat.obdStateBP
    s = self.settings
    m.enabled = s.enabled
    m.transport = s.transport if s.enabled and s.transport in TRANSPORTS else "none"
    m.link = self.link
    m.message = self.message
    m.adapter = self.elm.version if self.elm else ""
    m.protocol = self.elm.protocol if self.elm else ""
    m.bluetoothAvailable = self.bt_ok
    m.bluetoothMessage = "" if self.bt_ok else self.bt_msg
    m.usbDevices = usb_candidates()
    self.request_times = [t for t in self.request_times if now - t < 10.]
    m.requestsPerSecond = len(self.request_times) / 10.
    m.lastResponseAgeS = max(0., float(now - self.last_response)) if math.isfinite(self.last_response) else -1.
    m.catalog = self.catalog_desc
    m.polling = s.enabled and s.may_poll and self.elm is not None
    fresh = [(k, v) for k, v in sorted(self.values.items()) if now - v[3] < VALUE_STALE_S]
    vals = m.init("values", len(fresh))
    for out, (short, (name, value, unit, t, header, request)) in zip(vals, fresh, strict=True):
      out.name, out.shortName, out.value, out.unit = name, short, value, unit
      out.ageS, out.header, out.request = max(0., float(now - t)), header, request
    return dat


def main():
  params = Params()
  service = ObdService(params)
  cloudlog.info(f"obdd: catalog {service.catalog_desc}; bluetooth: {service.bt_msg}")
  pm = messaging.PubMaster(["obdStateBP"])
  while True:
    t0 = time.monotonic()
    pm.send("obdStateBP", service.step(t0))
    time.sleep(max(0., PUBLISH_PERIOD_S - (time.monotonic() - t0)))


if __name__ == "__main__":
  main()
