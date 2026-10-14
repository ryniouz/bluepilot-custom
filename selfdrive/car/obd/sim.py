"""
Custom: simulated ELM327 adapter (stream B).

Answers like a real adapter on a parked, charging Lightning, so the OBD service, the UI and tests
can run without a truck or a dongle (BPObdTransport = "simulated").
"""
import time

from openpilot.selfdrive.car.obd.transports import Transport, TransportError

# (request header, request) -> response data after the service+DID echo
SIM_RESPONSES = {
  ("7E4", "224801"): bytes.fromhex("7148"),     # 29000 * 0.002 = 58.0 %
  ("7E4", "224845"): bytes([116]),              # 58.0 %
  ("7E4", "224848"): bytes.fromhex("6590"),     # 52.0 kWh
  ("7E4", "224800"): bytes([77]),               # 27 C
  ("7E4", "224846"): bytes([72]),               # 22 C
  ("7E4", "224841"): bytes.fromhex("0F6E"),     # 3.950 V
  ("7E4", "224840"): bytes.fromhex("0F64"),     # 3.940 V
  ("7E4", "224810"): bytes.fromhex("1C20"),     # 36 months
  ("7E2", "22480D"): bytes.fromhex("8B10"),     # 356.00 V
  ("7E2", "22480B"): bytes.fromhex("FC18"),     # -20.0 A (into the pack)
  ("7E2", "22484D"): bytes([3]),
  ("7E2", "224851"): bytes([6]),                # AC level 2
  ("7E2", "22484A"): bytes.fromhex("8B10"),
  ("726", "22402A"): bytes([156]),              # 13.8 V
  ("726", "224028"): bytes([88]),
  ("726", "222813"): bytes.fromhex("02AE"),     # ~259 kPa
  ("726", "222814"): bytes.fromhex("02B0"),
  ("726", "222816"): bytes.fromhex("02A8"),
  ("726", "222815"): bytes.fromhex("02AA"),
}


def iso_tp_lines(resp_id: int, payload: bytes) -> list[str]:
  rid = f"{resp_id:03X}"
  if len(payload) <= 7:
    return [rid + bytes([len(payload)]).hex().upper() + payload.hex().upper()]
  lines = [rid + f"1{len(payload) >> 8:X}{len(payload) & 0xFF:02X}" + payload[:6].hex().upper()]
  rest, seq = payload[6:], 1
  while rest:
    lines.append(rid + f"2{seq & 0xF:X}" + rest[:7].hex().upper())
    rest, seq = rest[7:], seq + 1
  return lines


class SimTransport(Transport):
  kind = "simulated"

  def __init__(self, responses: dict | None = None, asleep: bool = False):
    self.responses = dict(SIM_RESPONSES if responses is None else responses)
    self.asleep = asleep
    self.header = "7E0"
    self.out = bytearray()
    self.is_open = False
    self.sent: list[str] = []

  def open(self):
    self.is_open = True

  def close(self):
    self.is_open = False

  def write(self, data: bytes):
    if not self.is_open:
      raise TransportError("not open")
    cmd = data.decode().strip().upper().replace(" ", "")
    self.sent.append(cmd)
    self.out += (self._answer(cmd) + "\r\r>").encode()

  def read(self, timeout: float) -> bytes:
    if not self.is_open:
      raise TransportError("not open")
    if not self.out:
      time.sleep(min(timeout, 0.01))
      return b""
    data, self.out = bytes(self.out), bytearray()
    return data

  def _answer(self, cmd: str) -> str:
    if cmd == "ATZ":
      return "\r\rELM327 v1.5 (simulated)"
    if cmd == "ATDP":
      return "ISO 15765-4 (CAN 11/500)"
    if cmd.startswith("ATSH"):
      self.header = cmd[4:]
      return "OK"
    if cmd.startswith("AT"):
      return "OK"
    if self.asleep:
      return "CAN ERROR"
    data = self.responses.get((self.header, cmd))
    if data is None:
      return "NO DATA"
    req = bytes.fromhex(cmd)
    payload = bytes([req[0] + 0x40]) + req[1:] + data
    return "\r".join(iso_tp_lines(int(self.header, 16) + 8, payload))
