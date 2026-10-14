"""
Console Maps page (System > Maps), in place of sunnypilot's OSM panel. Offline OpenStreetMap data for
speed limits and road names, run by mapd.

  Map data   region (country, plus a state in the US), last download, download progress, Update maps
  Space      how much the maps take, Delete maps
  Pick       a radio list of countries or US states, fetched from mapd's bounding-box lists; Canada and
             the United States first

The param writes are sunnypilot's (OsmLocal, OsmLocationName/Title, OsmStateName/Title, OsmDbUpdatesCheck,
OsmDownloadedDate), as are the download state (OSMDownloadLocations in /dev/shm params) and progress
(OSMDownloadProgress).
"""

from __future__ import annotations

import datetime
import os
import platform
import shutil
import threading
import time
from pathlib import Path

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import device, ui_state
from openpilot.system.hardware.hw import Paths
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console.form import Action, Choice, FormPage, Info, Meter, Nav, Note, Section
from bluepilot.ui.lib.theme import Console

MAP_PATH = Path(Paths.mapd_root()) / "offline"
BOXES_URL = "https://raw.githubusercontent.com/pfeiferj/openpilot-mapd/main/"
FIRST = ("CA", "US")


def fmt_size(n: int) -> str:
  return f"{n / 1024 ** 2:.0f} MB" if n < 1024 ** 3 else f"{n / 1024 ** 3:.1f} GB"


class MapsPage(FormPage):
  def __init__(self):
    super().__init__()
    self._mem = Params("/dev/shm/params") if platform.system() != "Darwin" else Params()
    self._size: int | None = None
    self._size_at = 0.0
    self._busy = ""                                          # "fetching" / "deleting"
    self._pick: tuple[str, list[tuple[str, str]]] | None = None  # (Country|State, [(ref, name)])

  def show_event(self):
    super().show_event()
    self._pick = None
    self._measure()

  # -- data -----------------------------------------------------------------------------------

  def _measure(self):
    def run():
      total = 0
      todo = [MAP_PATH] if MAP_PATH.exists() else []
      while todo:
        try:
          for e in os.scandir(todo.pop()):
            if e.is_file():
              total += e.stat().st_size
            elif e.is_dir():
              todo.append(Path(e.path))
        except OSError:
          pass
      self._size = total
    self._size_at = time.monotonic()
    threading.Thread(target=run, daemon=True).start()

  def _downloading(self) -> bool:
    try:
      return bool(self._mem.get("OSMDownloadLocations"))
    except Exception:
      return False

  # -- sections -------------------------------------------------------------------------------

  def sections(self) -> list[Section]:
    if self._pick is not None:
      return [self._picker()]
    downloading = self._downloading()
    if downloading:
      device._reset_interactive_timeout()
      if time.monotonic() - self._size_at > 2.0:
        self._measure()
    return [self._map_data(downloading), self._space(downloading)]

  def _map_data(self, downloading: bool) -> Section:
    country = self.p.get("OsmLocationTitle", "")
    state = self.p.get("OsmStateTitle", "") if self.p.get("OsmLocationName", "") == "US" else ""
    region = f"{state}, {country}" if state else country
    rows: list = [Nav(tr("Region"), tr("Choose where you drive") if not region else tr("Maps for this area"),
                      self._fetch_countries, value=tr("Loading…") if self._busy == "fetching" else (region or tr("None")))]
    pending = self.p.bool("OsmDbUpdatesCheck")
    if downloading or pending:
      prog = self.p.get("OSMDownloadProgress", None)
      total = prog.get("total_files", 0) if isinstance(prog, dict) else 0
      done = prog.get("downloaded_files", 0) if isinstance(prog, dict) else 0
      failed = total > 0 and not downloading and done < total
      if failed:
        rows.append(Info(tr("Download"), tr("Didn't finish"), dot=Console.WARNING))
        rows.append(Action(tr("Try again"), tr("Starts the download again"), tr("Retry"), self._ask_update, primary=True))
      else:
        frac = done / total if total else 0.0
        rows.append(Meter(tr("Downloading maps"), f"{done} / {total}" if total else tr("Starting…"), frac))
    elif region:
      ts = self.p.get("OsmDownloadedDate", "")
      when = ""
      try:
        if ts and float(ts) > 0:
          when = datetime.datetime.fromtimestamp(float(ts)).strftime("%b %-d, %Y")
      except (TypeError, ValueError):
        pass
      rows.append(Info(tr("Last downloaded"), when or tr("Not yet")))
      rows.append(Action(tr("Update maps"), tr("Downloads the latest map data"), tr("Update"), self._ask_update, primary=not when))
    version = self.p.get("MapdVersion", "")
    if version:
      rows.append(Info(tr("Map service"), str(version)))
    return Section(tr("Map data"), "map", rows,
                   note=tr("Offline maps give speed limits and road names, even without a connection."))

  def _space(self, downloading: bool) -> Section:
    size = self._size
    rows: list = [Info(tr("Maps on the comma"), tr("Measuring…") if size is None else fmt_size(size))]
    rows.append(Action(tr("Delete maps"), tr("Download again any time"),
                       tr("Deleting…") if self._busy == "deleting" else tr("Delete"), self._ask_delete, danger=True,
                       enabled=not downloading and not self._busy and bool(size)))
    return Section(tr("Space"), "storage", rows)

  def _picker(self) -> Section:
    kind, locs = self._pick
    key = "OsmLocation" if kind == "Country" else "OsmState"
    current = self.p.get(f"{key}Name", "")
    refs = [r for r, _ in locs]
    rows: list = [Nav(tr("Back"), "", self._cancel_pick, back=True)]
    if locs:
      rows.append(Choice(tr("Country") if kind == "Country" else tr("State"), [n for _, n in locs],
                         refs.index(current) if current in refs else -1, lambda i: self._choose(kind, locs[i]), radio=True))
    else:
      rows.append(Note(tr("Couldn't load the list. Check the connection and try again.")))
    return Section(tr("Choose a country") if kind == "Country" else tr("Choose a state"), "map", rows, wide=True)

  # -- actions --------------------------------------------------------------------------------

  def _fetch(self, kind: str):
    if self._busy:
      return
    self._busy = "fetching"

    def run():
      import requests
      url = BOXES_URL + ("nation_bounding_boxes.json" if kind == "Country" else "us_states_bounding_boxes.json")
      try:
        data = requests.get(url, timeout=10).json()
        locs = sorted(((k, v["full_name"]) for k, v in data.items()), key=lambda kv: kv[1])
      except Exception:
        locs = []
      if kind == "Country":
        locs = [kv for f in FIRST for kv in locs if kv[0] == f] + [kv for kv in locs if kv[0] not in FIRST]
      else:
        locs.insert(0, ("All", tr("All states (about 6 GB)")))
      self._pick = (kind, locs)
      self._offset = 0.0
      self._busy = ""
    threading.Thread(target=run, daemon=True).start()

  def _fetch_countries(self):
    if not self._downloading():
      self._fetch("Country")

  def _cancel_pick(self):
    if self._pick is not None and self._pick[0] == "State" and self.p.get("OsmLocationName", "") == "US" \
       and not self.p.get("OsmStateName", ""):
      for k in ("OsmLocationName", "OsmLocationTitle", "OsmLocal"):
        ui_state.params.remove(k)
    self._pick = None
    self._offset = 0.0

  def _choose(self, kind: str, loc: tuple[str, str]):
    ref, name = loc
    p = ui_state.params
    if kind == "Country":
      p.put_bool("OsmLocal", True)
      p.remove("OsmStateName")
      p.remove("OsmStateTitle")
    key = "OsmLocation" if kind == "Country" else "OsmState"
    p.put(f"{key}Name", ref)
    p.put(f"{key}Title", name)
    self.p.invalidate()
    self._pick = None
    self._offset = 0.0
    if ref == "US" and kind == "Country":
      self._fetch("State")
    else:
      self._ask_update()

  def _ask_update(self):
    self.confirm(tr("Download maps?"), tr("This can take a while. It runs in the background; Wi-Fi is best."),
                 tr("Download"), lambda: self.p.put("OsmDbUpdatesCheck", True))

  def _ask_delete(self):
    self.confirm(tr("Delete all maps?"), tr("Speed limits and road names from maps stop until you download them again."),
                 tr("Delete"), self._delete, danger=True)

  def _delete(self):
    self._busy = "deleting"

    def run():
      if MAP_PATH.exists():
        shutil.rmtree(MAP_PATH, ignore_errors=True)
      for k in ("OsmDownloadedDate", "OsmLocal", "OsmLocationName", "OsmLocationTitle", "OsmStateName", "OsmStateTitle"):
        ui_state.params.remove(k)
      self.p.invalidate()
      self._busy = ""
      self._measure()
    threading.Thread(target=run, daemon=True).start()
