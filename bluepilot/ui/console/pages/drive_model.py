"""
Drive > Driving model: the model in use with its download progress, a model picker, and model storage.

Replaces sunnypilot's Models panel and its tree dialog, plus BluePilot's "Clear crashed model" row. Same params:
ModelManager_DownloadIndex (pick), ModelManager_ActiveBundle (removed for the default model), ModelManager_Favs
(";"-joined refs), ModelManager_LastSyncTime (0 refreshes the list), ModelManager_ClearCache, and the offer to reset
calibration (CalibrationParams, LiveTorqueParameters) when the model generation changes.

The picker is a page of its own: favourites, then one row per folder; a folder lists its models newest first. Search
opens the sunnypilot text input and lists matches across folders.
"""

from __future__ import annotations

import os
import re
import time

import pyray as rl

from cereal import custom
from openpilot.selfdrive.ui.ui_state import device, ui_state
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.form import Action, Custom, FormPage, Info, Meter, Nav, Note, Section, ROW_SET
from bluepilot.ui.lib.theme import Console

try:
  from openpilot.sunnypilot.models.runners.constants import CUSTOM_MODEL_PATH
except Exception:  # pragma: no cover - dev machines without the sunnypilot model runners
  CUSTOM_MODEL_PATH = ""

DS = custom.ModelManagerSP.DownloadStatus
TYPE_LABELS = {"supercombo": "Driving", "navigation": "Navigation", "vision": "Vision", "policy": "Policy",
               "offPolicy": "Off-policy", "onPolicy": "On-policy"}
DEFAULT_REF = "Default"
HEADER_H = 112


def _folder(bundle) -> str:
  return next((o.value for o in bundle.overrides if o.key == "folder"), "")


def _cache_mb() -> float:
  try:
    if CUSTOM_MODEL_PATH and os.path.exists(CUSTOM_MODEL_PATH):
      return sum(os.path.getsize(os.path.join(CUSTOM_MODEL_PATH, f)) for f in os.listdir(CUSTOM_MODEL_PATH)) / 1024 ** 2
  except OSError:
    pass
  return 0.0


class DrivingModelPage(FormPage):
  def __init__(self):
    super().__init__()
    self._mode = "main"          # main | browse | folder | search
    self._folder_name = ""
    self._query = ""
    self._cache = (0.0, 0.0)     # (time, MB)
    self._fetching_t = 0.0
    self._back_rect: rl.Rectangle | None = None
    self._search_rect: rl.Rectangle | None = None
    self._prev_status = None
    self._status_changed = False

  def show_event(self):
    super().show_event()
    self._mode = "main"
    self._query = ""

  # -- model manager state --
  @property
  def mm(self):
    try:
      return ui_state.sm["modelManagerSP"]
    except Exception:
      return None

  def _bundles(self) -> list:
    mm = self.mm
    return list(mm.availableBundles) if mm is not None else []

  def _active_ref(self) -> str:
    mm = self.mm
    return mm.activeBundle.ref if mm is not None and mm.activeBundle.ref else DEFAULT_REF

  def _active_name(self) -> str:
    mm = self.mm
    return mm.activeBundle.displayName if mm is not None and mm.activeBundle.ref else tr("Default model")

  def _favs(self) -> set[str]:
    v = self.p.get("ModelManager_Favs", "") or ""
    return {f for f in str(v).split(";") if f}

  def _toggle_fav(self, ref: str):
    favs = self._favs()
    favs ^= {ref}
    self.p.put("ModelManager_Favs", ";".join(sorted(favs)))

  def _shown_bundle(self):
    """The bundle whose progress to show: the one downloading or failed, else the active one."""
    mm = self.mm
    if mm is None:
      return None
    sel = mm.selectedBundle
    if sel.ref and sel.status in (DS.downloading, DS.failed):
      return sel
    return mm.activeBundle if mm.activeBundle.ref else None

  def _folders(self) -> list[tuple[str, str, list]]:
    """(folder, updated, bundles newest first), newest folder first, as the sunnypilot picker orders them."""
    groups: dict[str, list] = {}
    for b in self._bundles():
      groups.setdefault(_folder(b), []).append(b)
    out = []
    for name, bs in sorted(groups.items(), key=lambda kv: max((b.index for b in kv[1]), default=-1), reverse=True):
      bs.sort(key=lambda b: b.index, reverse=True)
      m = re.search(r"\(([^)]*)\)[^(]*$", bs[0].displayName) if bs else None
      out.append((name or tr("Other"), m.group(1) if m else "", bs))
    return out

  # -- picking --
  def _pick(self, ref: str, name: str):
    if not ui_state.is_offroad():
      return
    if ref == self._active_ref():
      self._mode = "main"
      return
    mm = self.mm

    def go():
      if ref == DEFAULT_REF:
        self._remove("ModelManager_ActiveBundle")
        reset = True
      else:
        b = next((b for b in self._bundles() if b.ref == ref), None)
        if b is None:
          return
        self.p.put("ModelManager_DownloadIndex", int(b.index))
        reset = mm is not None and bool(mm.activeBundle.ref) and b.generation != mm.activeBundle.generation
      self._mode = "main"
      if reset:
        self.confirm(tr("Reset calibration too?"),
                     tr("The new model is downloading in the background. It's a different model generation, so we suggest " +
                        "resetting calibration. The truck recalibrates over the first few minutes of the next drive."),
                     tr("Reset"), self._reset_calibration)
    self.confirm(tr("Use") + f" {name}?",
                 tr("It downloads in the background and takes over on the next drive."), tr("Use this model"), go)

  def _reset_calibration(self):
    self._remove("CalibrationParams")
    self._remove("LiveTorqueParameters")

  def _remove(self, key: str):
    try:
      self.p._params.remove(key)
    except Exception:
      pass
    self.p.invalidate()

  def _search(self):
    try:
      from openpilot.system.ui.sunnypilot.widgets.input_dialog import InputDialogSP
      from openpilot.system.ui.widgets import DialogResult
    except Exception:
      return

    def done(result, text):
      if result == DialogResult.CONFIRM:
        self._query = (text or "").strip()
        self._mode = "search" if self._query else "browse"
        self._offset = 0.0
    InputDialogSP(tr("Search models"), "", current_text=self._query, callback=done).show()

  # -- header (picker views only) --
  def header(self, rect: rl.Rectangle) -> float:
    self._back_rect = self._search_rect = None
    if self._mode == "main":
      return 0.0
    y = rect.y
    back = rl.Rectangle(rect.x, y, 200, 80)
    D.button(back, tr("Back"), primary=False, size=D.LABEL)
    self._back_rect = back
    title = {"browse": tr("Choose a model"), "folder": self._folder_name,
             "search": tr("Results for") + f" \"{self._query}\""}[self._mode]
    sw = 240
    D.text(D.fit(title, D.H2, rect.width - back.width - sw - 80, semi=True), back.x + back.width + 32,
           y + (80 - D.H2) / 2 - 2, D.H2, semi=True)
    s = rl.Rectangle(rect.x + rect.width - 16 - sw, y, sw, 80)
    D.button(s, "", primary=False, size=D.LABEL)
    D.icon("search", s.x + 32, s.y + 22, 36, Console.TEXT_SECONDARY)
    D.text(tr("Search"), s.x + 84, s.y + (80 - D.LABEL) / 2 - 2, D.LABEL, semi=True)
    self._search_rect = s
    return HEADER_H

  def _handle_mouse_release(self, pos) -> bool:
    if self._confirm is None and not self._dragging:
      if self._back_rect is not None and D.hit(self._back_rect, pos):
        self._mode = {"folder": "browse", "search": "browse"}.get(self._mode, "main")
        self._offset = 0.0
        return True
      if self._search_rect is not None and D.hit(self._search_rect, pos):
        self._search()
        return True
    return super()._handle_mouse_release(pos)

  # -- sections --
  def sections(self):
    if self._mode == "browse":
      return self._browse_sections()
    if self._mode in ("folder", "search"):
      return self._list_sections()
    return self._main_sections()

  def _main_sections(self):
    mm = self.mm
    offroad = ui_state.is_offroad()
    rows: list = [Info(tr("In use"), self._active_name())]
    b = self._shown_bundle()
    downloading = b is not None and mm is not None and b.ref == mm.selectedBundle.ref and b.status == DS.downloading
    if b is not None:
      if b.status != self._prev_status:
        self._status_changed = self._prev_status is not None
        self._prev_status = b.status
      if downloading or b.status == DS.failed:
        rows.append(Info(tr("Downloading") if downloading else tr("Download failed"), b.displayName,
                         dot=Console.ACCENT if downloading else Console.DANGER))
      for m in b.models:
        t = TYPE_LABELS.get(str(m.type), str(m.type).title())
        pr = m.artifact.downloadProgress
        if pr.status == DS.downloading:
          rows.append(Meter(tr(t), f"{int(pr.progress)} %", pr.progress / 100.0))
        elif pr.status in (DS.downloaded, DS.cached):
          done = tr("From cache") if pr.status == DS.cached and self._status_changed else \
            tr("Downloaded") if self._status_changed else tr("Ready")
          rows.append(Info(tr(t), done, dot=Console.SUCCESS))
        elif pr.status == DS.failed:
          rows.append(Info(tr(t), tr("Failed"), dot=Console.DANGER))
        else:
          rows.append(Info(tr(t), tr("Waiting"), dot=Console.TEXT_GHOST))
    if downloading:
      device._reset_interactive_timeout()
    rows.append(Action(tr("Change model"), tr("Browse folders and favourites") if offroad else tr("Change it with the truck off"),
                       tr("Browse"), self._open_browse, primary=True, enabled=offroad))
    if mm is not None and mm.selectedBundle.ref and self.p.get("ModelManager_DownloadIndex") not in (None, ""):
      rows.append(Action(tr("Cancel download"), mm.selectedBundle.displayName, tr("Cancel"),
                         lambda: self._remove("ModelManager_DownloadIndex")))

    now = time.monotonic()
    if now - self._cache[0] > 2.0:
      self._cache = (now, _cache_mb())
    fetching = now - self._fetching_t < 4.0
    storage = Section(tr("Model storage"), "download", [
      Action(tr("Check for new models"), tr("Fetching the latest list") if fetching else tr("Refresh the model list"),
             tr("Check"), self._refresh, enabled=not fetching),
      Action(tr("Clear downloaded models"), f"{self._cache[1]:.0f} MB, " + tr("keeps the one in use"), tr("Clear"),
             self._clear_cache),
      Action(tr("Reset a crashed model"), tr("If the model won't start. Reboots."), tr("Reset"),
             self._clear_crashed, danger=True),
    ], note=tr("Use reset when the driving screen shows Communication Issue because the model never started."))
    return [Section(tr("Driving model"), "cpu", rows), storage]

  def _open_browse(self):
    self._mode = "browse"
    self._offset = 0.0

  def _refresh(self):
    self.p.put("ModelManager_LastSyncTime", 0)
    self._fetching_t = time.monotonic()

  def _clear_cache(self):
    def ok():
      self.p.put("ModelManager_ClearCache", True)
      self._cache = (0.0, 0.0)
    self.confirm(tr("Clear downloaded models?"),
                 tr("This deletes every downloaded model except the one in use. They download again if you pick them."),
                 tr("Clear"), ok, danger=True)

  def _clear_crashed(self):
    def ok():
      self._remove("ModelRunnerTypeCache")
      self._remove("ModelManager_ActiveBundle")
      try:
        self.p._params.put_bool("DoReboot", True)
      except Exception:
        self.p.put("DoReboot", True)
    self.confirm(tr("Reset the model and reboot?"),
                 tr("Clears the model runner cache and goes back to the default model, then reboots. " +
                    "This fixes a Communication Issue alert when the model fails to start."),
                 tr("Reset and reboot"), ok, danger=True)

  # picker: favourites and folders
  def _model_row(self, ref: str, name: str, short: str, favs: set[str]) -> Custom:
    active = ref == self._active_ref()
    mm = self.mm
    pending = mm is not None and ref == mm.selectedBundle.ref and mm.selectedBundle.status == DS.downloading

    def draw(r: rl.Rectangle):
      star = rl.Rectangle(r.x + r.width - 88, r.y + (ROW_SET - 88) / 2, 88, 88)
      if active:
        D.icon("check", r.x, r.y + (ROW_SET - 40) / 2, 40, Console.ACCENT)
      tx = r.x + 64
      tag = tr("In use") if active else tr("Downloading") if pending else ""
      tw = D.text_w(tag, 26, semi=True) + 28 if tag else 0
      room = star.x - tx - 16 - tw
      D.text(D.fit(name, D.BODY, room, semi=True), tx, r.y + 14, D.BODY,
             Console.ACCENT_TEXT if active else Console.TEXT_PRIMARY, semi=True)
      if short:
        D.text(D.fit(short, D.LABEL, room), tx, r.y + 58, D.LABEL, Console.TEXT_MUTED)
      if tag:
        K.tag(star.x - tw - 8, r.y + (ROW_SET - 44) / 2, tag, accent=True)
      hits = []
      if ref != DEFAULT_REF:
        on = ref in favs
        _star(star.x + 44, star.y + 44, 22, on, Console.WARNING if on else Console.TEXT_MUTED)
        hits.append((star, lambda: self._toggle_fav(ref)))
      hits.append((rl.Rectangle(r.x, r.y, star.x - r.x, r.height), lambda: self._pick(ref, name)))
      return hits
    return Custom(ROW_SET, draw)

  def _browse_sections(self):
    favs = self._favs()
    fav_rows = [self._model_row(b.ref, b.displayName, b.internalName, favs) for b in self._bundles() if b.ref in favs]
    out = [Section(tr("Recommended"), "check", [
      self._model_row(DEFAULT_REF, tr("Default model"), tr("Ships with this software"), favs)]),
    ]
    if fav_rows:
      out.append(Section(tr("Favourites"), "bookmark", fav_rows))
    folders = self._folders()
    if folders:
      out.append(Section(tr("All models"), "list", [
        Nav(name, (tr("Updated") + " " + upd) if upd else f"{len(bs)} " + tr("models"),
            lambda n=name: self._open_folder(n), value=str(len(bs)))
        for name, upd, bs in folders
      ]))
    else:
      out.append(Section(tr("All models"), "list", [
        Note(tr("No model list yet. Connect to the internet and use Check for new models."))]))
    if not fav_rows:
      out.append(Section(tr("Favourites"), "bookmark", [
        Note(tr("Tap the star next to a model to keep it here."))]))
    return out

  def _open_folder(self, name: str):
    self._folder_name = name
    self._mode = "folder"
    self._offset = 0.0

  def _list_sections(self):
    favs = self._favs()
    if self._mode == "folder":
      bs = next((b for n, _, b in self._folders() if n == self._folder_name), [])
      return [Section(tr("Models"), "list", [self._model_row(b.ref, b.displayName, b.internalName, favs) for b in bs],
                      wide=True)]
    try:
      from openpilot.system.ui.sunnypilot.widgets.helpers.fuzzy_search import search_from_list
    except Exception:
      def search_from_list(q, items):
        return [i for i in items if q.lower() in i.lower()]
    hits = [b for b in self._bundles() if search_from_list(self._query, [b.displayName, b.internalName])]
    rows: list = [self._model_row(b.ref, b.displayName, b.internalName, favs) for b in hits]
    return [Section(tr("Models"), "search", rows or [Note(tr("No models match. Try a shorter word."))], wide=True)]


def _star(cx: float, cy: float, r: float, filled: bool, color: rl.Color):
  try:
    from openpilot.system.ui.sunnypilot.widgets.helpers.star_icon import draw_star
    draw_star(cx, cy, r, filled, color)
  except Exception:
    D.icon("bookmark", cx - r, cy - r, 2 * r, color)
