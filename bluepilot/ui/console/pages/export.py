"""
Console Data export page (Connect > Data export), built from the Console form components.

  Home server  the data export bridge for Citadel (BPBridgeEnabled, BPKeepUntilSynced), its Wi-Fi address and token
  Web portal   the browser portal (bp_portal, EnableWebRoutesServer on BPPortalPort), its address and a QR code

The web portal used to be its own page ("BluePilot Portal"). Citadel's comma app now covers settings, params,
drives, live data and file downloads through the bridge, but the portal still does things nothing else on the
truck does: playing drives with every camera in a browser (HLS), exporting MP4 clips, reading manager logs and
cereal messages, and backing up or restoring params to a file. So it stays, as one section of this page.
Rows whose params this build doesn't have are left out.
"""

from __future__ import annotations

import socket
import time

import pyray as rl

from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console import draw as D
from bluepilot.ui.console.form import Action, Custom, FormPage, Info, Note, Section, Toggle
from bluepilot.ui.lib import bridge_status as bridge
from bluepilot.ui.lib.theme import Console

try:
  import qrcode
  _HAS_QR = True
except ImportError:
  _HAS_QR = False

IP_EVERY_S = 5.0
QR_PX = 240


def local_ip() -> str:
  try:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
      sock.connect(("10.255.255.255", 1))  # no packet is sent; picks the outbound interface
      return sock.getsockname()[0]
  except OSError:
    return ""


def qr_matrix(text: str) -> list[list[bool]]:
  if not _HAS_QR or not text:
    return []
  qr = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_L)
  qr.add_data(text)
  qr.make(fit=True)
  return qr.get_matrix()


class ExportPage(FormPage):
  def __init__(self):
    super().__init__()
    self._ip, self._ip_at = "", -1e9
    self._show_token = False
    self._qr_text, self._qr = "", []

  def show_event(self):
    super().show_event()
    self._ip_at = -1e9
    self._show_token = False

  def _local_ip(self) -> str:
    now = time.monotonic()
    if now - self._ip_at >= IP_EVERY_S:
      self._ip, self._ip_at = local_ip(), now
    return self._ip

  # -- sections -----------------------------------------------------------------------------

  def sections(self) -> list[Section]:
    return [self._server_section(), self._portal_section()]

  def _server_section(self) -> Section:
    p = self.p
    if not p.has("BPBridgeEnabled"):
      return Section(tr("Home server"), "export", [Note(tr("Data export for Citadel comes with the data export update."))])
    on = p.bool("BPBridgeEnabled")
    rows: list = [Toggle(tr("Data export"), tr("Drives and live data for Citadel"), on,
                         p.flip("BPBridgeEnabled"))]
    if p.has("BPKeepUntilSynced"):
      rows.append(Toggle(tr("Keep drives until synced"), tr("Cleanup waits for Citadel"),
                         p.bool("BPKeepUntilSynced", True), p.flip("BPKeepUntilSynced", True)))
    if on:
      running = bridge.status() is not None
      rows.append(Info(tr("Status"), tr("Running") if running else tr("Starting"), Console.SUCCESS if running else Console.TEXT_GHOST))
      ip, port = self._local_ip(), p.get("BPBridgePort", None) if p.has("BPBridgePort") else None
      rows.append(Info(tr("Address"), f"{ip}:{port}" if ip and port else (tr("No Wi-Fi") if port else tr("Not available"))))
      token = str(p.get("BPBridgeToken", "") or "") if p.has("BPBridgeToken") else ""
      if token:
        shown = (token if len(token) <= 16 else f"{token[:8]}…{token[-6:]}") if self._show_token else "•" * 12
        rows.append(Action(tr("Access token"), shown, tr("Hide") if self._show_token else tr("Show"),
                           lambda: setattr(self, "_show_token", not self._show_token)))
      rows.append(Note(tr("Enter the address and token in Citadel's comma app. Read-only, and only on your Wi-Fi.")))
    return Section(tr("Home server"), "export", rows)

  def _portal_section(self) -> Section:
    p = self.p
    if not p.has("EnableWebRoutesServer"):
      return Section(tr("Web portal"), "screen", [])
    on = p.bool("EnableWebRoutesServer")
    rows: list = [Toggle(tr("Web portal"), tr("Drives and video in a browser"), on, p.flip("EnableWebRoutesServer"))]
    if on:
      ip = self._local_ip()
      port = p.int("BPPortalPort", 8088) if p.has("BPPortalPort") else 8088
      url = f"http://{ip}:{port}" if ip else ""
      rows.append(Info(tr("Address"), url or tr("Connect to Wi-Fi first")))
      if url and _HAS_QR:
        rows.append(Custom(QR_PX + 40, lambda r, u=url: self._draw_qr(r, u)))
    rows.append(Note(tr("On a phone or laptop on the same Wi-Fi: play drives with every camera, export video clips, " +
                        "read logs and back up or restore settings.")))
    return Section(tr("Web portal"), "screen", rows)

  def _draw_qr(self, r: rl.Rectangle, url: str):
    if url != self._qr_text:
      self._qr_text, self._qr = url, qr_matrix(url)
    n = len(self._qr)
    if not n:
      return None
    quiet = 16
    box = rl.Rectangle(r.x, r.y + 20, QR_PX, QR_PX)
    rl.draw_rectangle_rounded(box, 0.06, 6, rl.WHITE)  # a QR needs a light ground in both themes
    cell = (QR_PX - 2 * quiet) / n
    for y, line in enumerate(self._qr):
      for x, dark in enumerate(line):
        if dark:
          rl.draw_rectangle_rec(rl.Rectangle(box.x + quiet + x * cell, box.y + quiet + y * cell, cell + 0.5, cell + 0.5),
                                rl.BLACK)
    tx = box.x + QR_PX + 32
    D.text(tr("Scan with your phone"), tx, box.y + QR_PX / 2 - 44, D.BODY, semi=True)
    D.text(D.fit(url, D.LABEL, r.x + r.width - tx), tx, box.y + QR_PX / 2 + 4, D.LABEL, Console.TEXT_MUTED)
    return None
