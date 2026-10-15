"""
Custom: ELM327 client for read-only Ford enhanced-PID requests (stream B).

Talks the ELM327 command set over any Transport. Headers are on (ATH1) so every response line is
"<CAN id><ISO-TP frame>"; this module reassembles single and multi-frame ISO-TP responses itself
and checks that the reply is the positive response to what was asked.

Only read services (01, 09, 22) can be sent: check_request() rejects anything else, and the
adapter is never put in monitor or transmit-raw modes.
"""
import time
from dataclasses import dataclass

from openpilot.selfdrive.car.obd.catalog import check_request
from openpilot.selfdrive.car.obd.transports import Transport, TransportError

PROMPT = b">"
INIT_COMMANDS = ("ATE0", "ATL0", "ATS0", "ATH1", "ATAT1", "ATST32")  # echo off, no spaces, headers on, adaptive timing
NO_DATA = ("NO DATA", "CAN ERROR", "UNABLE TO CONNECT", "BUS INIT", "BUS BUSY", "STOPPED", "ERR")
NRC = {0x10: "general reject", 0x11: "service not supported", 0x12: "not supported", 0x13: "bad length",
       0x22: "conditions not correct", 0x31: "out of range", 0x33: "security access denied", 0x78: "pending"}


class ElmError(Exception):
  pass


class NoData(ElmError):
  """The car did not answer (asleep, or the module doesn't support the request)."""


class Negative(ElmError):
  def __init__(self, nrc: int):
    super().__init__(f"negative response 0x{nrc:02X} ({NRC.get(nrc, 'unknown')})")
    self.nrc = nrc


@dataclass
class Frame:
  can_id: int
  data: bytes


def parse_lines(text: str) -> list[Frame]:
  frames = []
  for line in text.replace("\r", "\n").split("\n"):
    s = line.strip().replace(" ", "").upper()
    if not s or s.startswith("SEARCHING"):
      continue
    if any(s.startswith(m.replace(" ", "")) for m in NO_DATA) or s == "?":
      continue
    if len(s) < 5 or any(c not in "0123456789ABCDEF" for c in s):
      continue
    id_len = 8 if s.startswith("18DA") else 3  # Ford EV modules use 11-bit ids; 29-bit diagnostic ids are 18DAxxxx
    can_id, payload = s[:id_len], s[id_len:]
    if len(payload) % 2:
      continue
    frames.append(Frame(int(can_id, 16), bytes.fromhex(payload)))
  return frames


def reassemble(frames: list[Frame], can_id: int) -> bytes | None:
  """ISO-TP reassembly of the frames from one ECU. Returns the UDS payload or None."""
  out = bytearray()
  total = None
  for f in (f for f in frames if f.can_id == can_id):
    if not f.data:
      continue
    pci = f.data[0] >> 4
    if pci == 0:  # single frame
      n = f.data[0] & 0x0F
      return bytes(f.data[1:1 + n])
    if pci == 1:  # first frame
      total = ((f.data[0] & 0x0F) << 8) | f.data[1]
      out = bytearray(f.data[2:])
    elif pci == 2 and total is not None:  # consecutive frame
      out += f.data[1:]
    if total is not None and len(out) >= total:
      return bytes(out[:total])
  return None


FUNCTIONAL = "7DF"


def response_ids(header: str) -> tuple[int, ...]:
  if header.upper() == FUNCTIONAL:  # broadcast: any engine-range module may answer
    return tuple(range(0x7E8, 0x7F0))
  return (int(header, 16) + 8,)


class Elm327:
  def __init__(self, transport: Transport, timeout: float = 2.0):
    self.t = transport
    self.timeout = timeout
    self.header: str | None = None
    self.version = ""
    self.protocol = ""

  def command(self, cmd: str, timeout: float | None = None) -> str:
    self.t.write(cmd.encode() + b"\r")
    buf = bytearray()
    end = time.monotonic() + (timeout or self.timeout)
    while PROMPT not in buf:
      left = end - time.monotonic()
      if left <= 0:
        raise TransportError(f"no prompt after {cmd!r}")
      buf += self.t.read(left)
    return buf[:buf.index(PROMPT)].decode(errors="replace").strip()

  def initialize(self, protocol: str = "6") -> None:
    reply = self.command("ATZ", timeout=5.0)  # reset prints the version banner
    self.version = next((ln.strip() for ln in reply.splitlines() if "ELM" in ln.upper()), reply.strip()[:40])
    for c in INIT_COMMANDS + (f"ATSP{protocol}",):
      r = self.command(c)
      if "OK" not in r.upper():
        raise ElmError(f"adapter rejected {c}: {r!r}")
    self.protocol = self.command("ATDP")
    self.header = None

  def set_header(self, header: str) -> None:
    if header == self.header:
      return
    r = self.command(f"ATSH{header}")
    if "OK" not in r.upper():  # a late data frame arriving here is not an ack
      self.header = None
      raise ElmError(f"ATSH{header} not acknowledged: {r[:40]!r}")
    self.header = header

  def request(self, header: str, request: str) -> bytes:
    """Send one read request; returns the data after the echoed service+DID."""
    req = check_request(request)
    self.set_header(header)
    raw = self.command(req)
    rids = response_ids(header)
    frames = parse_lines(raw)
    expect = bytes([int(req[:2], 16) + 0x40]) + bytes.fromhex(req)[1:]
    negative = None
    for rid in rids:  # functional requests: the first module with a positive answer wins
      payload = reassemble(frames, rid)
      if payload is None:
        continue
      if payload[0] == 0x7F:
        negative = negative or Negative(payload[2] if len(payload) > 2 else 0)
        continue
      if payload.startswith(expect):
        return payload[len(expect):]
      if len(rids) == 1:
        raise ElmError(f"unexpected response {payload[:6].hex()} to {req}")
    if negative is not None:
      raise negative
    if any(f.can_id in rids for f in frames):
      raise ElmError(f"incomplete response to {req}")
    raise NoData(raw.strip()[:40] or "no response")
