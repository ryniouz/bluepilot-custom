"""
Console Updates page (System > Updates): BluePilot updates from Lucas's own repository.

The updater (system/updated/updated.py, Custom block) points git's origin at BPUpdateRepo
(default github.com/ryniouz/bluepilot-custom) before every check and download, and follows
BPUpdateBranch when one is picked here. This page shows what is installed and what is waiting,
and drives the updater the same way the stock Software panel does: SIGUSR1 to check, SIGHUP to
download, DoReboot to install.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.home import _param
from bluepilot.ui.lib.theme import Console, roundness

GAP = 32
ROW = 84
BRANCH_ROW = 96
DEFAULT_REPO = "https://github.com/ryniouz/bluepilot-custom.git"


def _text(v) -> str:
  if isinstance(v, bytes):
    v = v.decode(errors="ignore")
  return str(v or "").strip("\x00").strip()


def repo_name(url: str) -> str:
  url = url.removesuffix(".git").rstrip("/")
  parts = url.split("/")
  return "/".join(parts[-2:]) if len(parts) >= 2 else url


class UpdatesPage(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._hits: list[tuple[rl.Rectangle, Callable[[], None]]] = []
    self._picking = False
    self._requested = ""

  def show_event(self):
    super().show_event()
    self._picking = False

  # -- params -------------------------------------------------------------------------------

  def _get(self, key: str) -> str:
    return _text(_param(self._params, key, ""))

  def branch(self) -> str:
    return self._get("BPUpdateBranch") or self._get("UpdaterTargetBranch") or self._get("GitBranch")

  def branches(self) -> list[str]:
    raw = self._get("UpdaterAvailableBranches")
    return [b for b in (x.strip() for x in raw.split(",")) if b] if raw else []

  # -- render -------------------------------------------------------------------------------

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    left, right = K.split_cols(rect, [1.15, 1])
    left.width -= GAP / 2
    right.x += GAP / 2
    right.width -= GAP / 2
    self._status_card(left)
    if self._picking:
      self._branch_picker(right)
    else:
      self._source_card(right)

  def _status_card(self, r: rl.Rectangle):
    D.card(r)
    p = D.CARD_PAD
    x, y, right = r.x + p, r.y + p, r.x + r.width - p
    available = bool(_param(self._params, "UpdateAvailable", False))
    fetch_ready = bool(_param(self._params, "UpdaterFetchAvailable", False))
    state = self._get("UpdaterState")
    busy = state not in ("", "idle")
    if available:
      title, color = tr("Update ready to install"), Console.ACCENT
    elif fetch_ready:
      title, color = tr("Update available"), Console.ACCENT
    elif busy:
      title, color = state[:1].upper() + state[1:].rstrip("."), Console.ACCENT
    else:
      title, color = tr("Up to date"), Console.SUCCESS
    D.dot(x + 12, y + D.H2 / 2 + 2, 12, color)
    D.text(D.fit(title, D.H2, r.width - 2 * p - 40, semi=True), x + 40, y, D.H2, semi=True)
    y += 84

    current = self._get("UpdaterCurrentDescription") or self._get("Version")
    new = self._get("UpdaterNewDescription")
    rows = [(tr("Installed"), current.split(" / ")[0] if current else "–")]
    if new and (available or fetch_ready):
      rows.append((tr("New version"), new.split(" / ")[0]))
    last = _param(self._params, "LastUpdateTime", None)
    if last is not None:
      try:
        rows.append((tr("Last checked"), last.strftime("%b %-d, %-I:%M %p")))
      except Exception:
        pass
    for label, value in rows:
      K.hline(x, right, y)
      D.text(label, x, y + 24, D.BODY, Console.TEXT_MUTED)
      D.text_right(D.fit(value, D.BODY, r.width * 0.55, semi=True), right, y + 24, D.BODY, semi=True)
      y += ROW

    by = r.y + r.height - p - D.CONTROL_H
    bw = r.width - 2 * p
    if available:
      b = rl.Rectangle(x, by, bw, D.CONTROL_H)
      D.button(b, tr("Install and restart"), primary=True)
      self._hits.append((b, self._install))
      if ui_state.started:
        D.text(tr("Installs once the truck is parked."), x, by - 48, D.LABEL, Console.TEXT_MUTED)
    elif fetch_ready:
      b = rl.Rectangle(x, by, bw, D.CONTROL_H)
      D.button(b, tr("Download"), primary=True)
      self._hits.append((b, self._download))
    else:
      b = rl.Rectangle(x, by, bw, D.CONTROL_H)
      D.button(b, tr("Checking…") if busy else tr("Check for updates"), primary=False)
      if not busy:
        self._hits.append((b, self._check))

  def _source_card(self, r: rl.Rectangle):
    D.card(r)
    p = D.CARD_PAD
    x, y, right = r.x + p, r.y + p, r.x + r.width - p
    D.icon("code", x, y - 2, 44, Console.TEXT_SECONDARY)
    D.text(tr("Source"), x + 64, y, D.H2, semi=True)
    y += 92
    repo = self._get("BPUpdateRepo") or DEFAULT_REPO
    D.text(tr("Repository"), x, y, D.LABEL, Console.TEXT_MUTED)
    D.text(D.fit(repo_name(repo), D.BODY, r.width - 2 * p, semi=True), x, y + 40, D.BODY, semi=True)
    y += 112
    K.hline(x, right, y)
    y += 24
    D.text(tr("Branch"), x, y, D.LABEL, Console.TEXT_MUTED)
    D.text(D.fit(self.branch() or "–", D.BODY, r.width - 2 * p, semi=True), x, y + 40, D.BODY, semi=True)
    y += 112
    K.hline(x, right, y)
    for i, ln in enumerate(D.wrap(tr("Updates come only from this repository, never from upstream BluePilot."), D.LABEL,
                                  r.width - 2 * p, 2)):
      D.text(ln, x, y + 24 + i * 40, D.LABEL, Console.TEXT_MUTED)
    b = rl.Rectangle(x, r.y + r.height - p - D.CONTROL_H, r.width - 2 * p, D.CONTROL_H)
    D.button(b, tr("Change branch"), primary=False)
    self._hits.append((b, self._open_picker))

  def _branch_picker(self, r: rl.Rectangle):
    D.card(r)
    p = D.CARD_PAD
    x, y = r.x + p, r.y + p
    D.text(tr("Pick a branch"), x, y, D.H2, semi=True)
    close = rl.Rectangle(r.x + r.width - p - 160, y - 14, 160, 64)
    D.button(close, tr("Done"), primary=False, size=D.LABEL)
    self._hits.append((close, self._close_picker))
    y += 84
    branches = self.branches()
    if not branches:
      for i, ln in enumerate(D.wrap(tr("The branch list fills in after the first check for updates."), D.BODY,
                                    r.width - 2 * p, 3)):
        D.text(ln, x, y + i * 48, D.BODY, Console.TEXT_MUTED)
      return
    current = self.branch()
    for name in branches:
      if y + BRANCH_ROW > r.y + r.height - p:
        break
      row = rl.Rectangle(x - 12, y, r.width - 2 * p + 24, BRANCH_ROW - 8)
      on = name == current
      if on:
        rl.draw_rectangle_rounded(row, roundness(row, 14), 8, Console.ACCENT_TINT)
      D.text(D.fit(name, D.BODY, row.width - 48, semi=on), x + 12, y + (row.height - D.BODY) / 2 - 2, D.BODY,
             Console.ACCENT_TEXT if on else None, semi=on)
      self._hits.append((row, lambda n=name: self._pick(n)))
      y += BRANCH_ROW

  # -- actions ------------------------------------------------------------------------------

  def _check(self):
    os.system("pkill -SIGUSR1 -f system.updated.updated")

  def _download(self):
    os.system("pkill -SIGHUP -f system.updated.updated")

  def _install(self):
    if ui_state.started:
      return
    self._params.put_bool("DoReboot", True)

  def _open_picker(self):
    self._picking = True

  def _close_picker(self):
    self._picking = False

  def _pick(self, name: str):
    try:
      self._params.put("BPUpdateBranch", name)
      self._params.put("UpdaterTargetBranch", name)
    except Exception:
      return
    self._picking = False
    self._check()

  def _handle_mouse_release(self, pos) -> bool:
    for r, fn in self._hits:
      if D.hit(r, pos):
        fn()
        return True
    return False
