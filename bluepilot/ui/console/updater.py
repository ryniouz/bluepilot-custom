"""
Console OS update screen. AGNOS runs an updater before the UI starts when the OS needs updating
(launch_chffrplus.sh agnos_init -> system/hardware/tici/updater). That script now prefers
system/hardware/tici/updater_console, a zipapp of this module built by tools/console_updater/build.py,
and falls back to the stock updater_magic when the Console one can't start (`--check`).

  Prompt    the logo, "Software update needed", why, and Connect to Wi-Fi / Install
  Wi-Fi     the stock Wi-Fi list in a Console card, with Back (only when the Wi-Fi widget loads; the button
            is hidden otherwise and Install still works on a saved network or cellular)
  Progress  the logo on black like the boot screens, what is being installed, and a thick squared Console
            bar with the percentage; on failure a calm message and Reboot

The update itself is the stock one: agnos.py --swap <manifest>, its "text: value" progress lines, and a
reboot on success. This module avoids importing Params (a compiled module the zipapp can't carry).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from enum import IntEnum

import pyray as rl

from openpilot.system.hardware import HARDWARE
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.boot import apply_saved_theme, logo_texture
from bluepilot.ui.lib.theme import Console

PAD = 64
BTN_H = 120
BAR_H = 48
PROMPT_LOGO_H = 240
PROGRESS_LOGO_H = 300


class Screen(IntEnum):
  PROMPT = 0
  WIFI = 1
  PROGRESS = 2


def tidy(text: str) -> str:
  """agnos.py's "Installing system" / "Downloading..." without the dots, capitalised."""
  text = text.strip().rstrip(".")
  return text[:1].upper() + text[1:] if text else ""


def parse_progress(line: str) -> tuple[str, int | None] | None:
  """'Installing system: 45' -> ('Installing system', 45); None for lines that aren't progress."""
  parts = line.strip().split(":")
  if len(parts) != 2:
    return None
  try:
    return parts[0], int(float(parts[1]))
  except ValueError:
    return parts[0], None


def _wifi_ui(agnos_py: str):
  """The stock Wi-Fi list. It needs Params, a compiled module the zipapp can't carry, so inside the zipapp it
  borrows the installed tree's (agnos.py is <tree>/system/hardware/tici/agnos.py); None if neither works."""
  for attempt in range(2):
    try:
      from openpilot.system.ui.lib.wifi_manager import WifiManager
      from openpilot.system.ui.widgets.network import WifiManagerUI
      return WifiManagerUI(WifiManager())
    except Exception:
      if attempt == 0:
        try:
          import openpilot.common
          openpilot.common.__path__.append(os.path.join(os.path.dirname(os.path.abspath(agnos_py)), *[".."] * 3, "common"))
        except Exception:
          return None
  return None


class ConsoleUpdater(Widget):
  def __init__(self, updater_path: str, manifest_path: str):
    super().__init__()
    apply_saved_theme()
    self.updater = updater_path
    self.manifest = manifest_path
    self.current_screen = Screen.PROMPT
    self.progress_value = 0
    self.progress_text = "Loading"
    self.show_reboot_button = False
    self.process: subprocess.Popen | None = None
    self.wifi_manager_ui = _wifi_ui(updater_path)
    self._hits: list[tuple[rl.Rectangle, object]] = []

  def set_current_screen(self, screen: Screen):
    self.current_screen = screen

  def install_update(self):
    self.set_current_screen(Screen.PROGRESS)
    self.progress_value = 0
    self.progress_text = "Downloading"
    self.show_reboot_button = False
    threading.Thread(target=self._run_update_process, daemon=True).start()

  def _run_update_process(self):
    self.process = subprocess.Popen([self.updater, "--swap", self.manifest], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, bufsize=1)
    if self.process.stdout is not None:
      for line in self.process.stdout:
        p = parse_progress(line)
        if p is not None:
          self.progress_text = p[0]
          if p[1] is not None:
            self.progress_value = p[1]
    if self.process.wait() == 0:
      HARDWARE.reboot()
    else:
      self.progress_text = "Update failed"
      self.show_reboot_button = True

  # -- drawing ----------------------------------------------------------------------------------

  def _logo(self, cx: float, y: float, h: int) -> float:
    tex = logo_texture(h)
    if tex is not None:
      rl.draw_texture(tex, int(cx - tex.width / 2), int(y), rl.WHITE)
    return y + h

  def _button(self, r: rl.Rectangle, label: str, fn, primary: bool = True):
    D.button(r, label, primary=primary)
    self._hits.append((r, fn))

  def render_prompt_screen(self, rect: rl.Rectangle):
    cx = rect.x + rect.width / 2
    y = self._logo(cx, rect.y + 96, PROMPT_LOGO_H) + 64
    D.text_center("Software update needed", cx, y, D.H1, semi=True)
    y += 92
    body = "The operating system needs an update before the comma can start. It is about 1 GB, so Wi-Fi is fastest."
    for ln in D.wrap(body, D.BODY - 2, min(1400, rect.width - 2 * PAD), 2):
      D.text_center(ln, cx, y, D.BODY - 2, Console.TEXT_SECONDARY)
      y += 52
    bw = min(560, (rect.width - 3 * PAD) / 2)
    by = rect.y + rect.height - PAD - BTN_H
    if self.wifi_manager_ui is not None:
      self._button(rl.Rectangle(cx - bw - PAD / 2, by, bw, BTN_H), "Connect to Wi-Fi",
                   lambda: self.set_current_screen(Screen.WIFI), primary=False)
      self._button(rl.Rectangle(cx + PAD / 2, by, bw, BTN_H), "Install", self.install_update)
    else:
      self._button(rl.Rectangle(cx - bw / 2, by, bw, BTN_H), "Install", self.install_update)

  def render_wifi_screen(self, rect: rl.Rectangle):
    card = rl.Rectangle(rect.x + PAD, rect.y + PAD, rect.width - 2 * PAD, rect.height - BTN_H - 3 * PAD)
    D.card(card)
    if self.wifi_manager_ui is not None:
      self.wifi_manager_ui.render(rl.Rectangle(card.x + D.CARD_PAD, card.y, card.width - 2 * D.CARD_PAD, card.height))
    self._button(rl.Rectangle(rect.x + PAD, rect.y + rect.height - PAD - BTN_H, 360, BTN_H), "Back",
                 lambda: self.set_current_screen(Screen.PROMPT), primary=False)

  def render_progress_screen(self, rect: rl.Rectangle):
    cx = rect.x + rect.width / 2
    failed = self.show_reboot_button
    y = self._logo(cx, rect.y + (140 if failed else 180), PROGRESS_LOGO_H) + 96
    bar_w = min(1200, rect.width - 4 * PAD)
    x0 = cx - bar_w / 2
    if failed:
      D.text_center("Update didn't finish", cx, y, D.H1, Console.WARNING, semi=True)
      D.text_center("Nothing is lost. Reboot to try the update again.", cx, y + 84, D.BODY - 2, Console.TEXT_SECONDARY)
      bw = 420
      self._button(rl.Rectangle(cx - bw / 2, rect.y + rect.height - PAD - BTN_H, bw, BTN_H), "Reboot", HARDWARE.reboot)
      return
    pct = max(0, min(100, int(self.progress_value)))
    D.text(D.fit(tidy(self.progress_text), D.H2, bar_w - 220, semi=True), x0, y, D.H2, semi=True)
    D.text_right(f"{pct} %", x0 + bar_w, y, D.H2, Console.TEXT_SECONDARY, semi=True)
    y += 84
    K.bar(rl.Rectangle(x0, y, bar_w, BAR_H), pct / 100.0, Console.ACCENT)
    D.text_center("Keep the comma plugged in. It restarts when it's done.", cx, y + BAR_H + 48, D.LABEL, Console.TEXT_MUTED)

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    rl.draw_rectangle_rec(rect, rl.BLACK)  # black like the boot screens before and after it
    if self.current_screen == Screen.PROMPT:
      self.render_prompt_screen(rect)
    elif self.current_screen == Screen.WIFI:
      self.render_wifi_screen(rect)
    else:
      self.render_progress_screen(rect)

  def _handle_mouse_release(self, pos) -> bool:
    for r, fn in self._hits:
      if D.hit(r, pos):
        fn()
        return True
    return False


def main():
  if "--check" in sys.argv:  # system/hardware/tici/updater: everything imports, so this screen can start
    print("ok")
    return
  if len(sys.argv) < 3:
    print("Usage: updater_console <agnos.py> <manifest.json>")
    sys.exit(1)
  try:
    gui_app.init_window("System Update")
    gui_app.push_widget(ConsoleUpdater(sys.argv[1], sys.argv[2]))
    for _ in gui_app.render():
      pass
  finally:
    gui_app.close()


if __name__ == "__main__":
  main()
