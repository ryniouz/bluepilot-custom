"""
Custom: byte transports for an ELM327-compatible OBD adapter (stream B).

- wifi:      TCP to the adapter (ELM327 Wi-Fi dongles listen on 192.168.0.10:35000), or to a
             Bluetooth-to-TCP bridge on another device in the truck.
- usb:       a USB serial adapter (/dev/ttyUSB*, /dev/ttyACM*).
- bluetooth: classic Bluetooth serial (RFCOMM). Needs a kernel with Bluetooth; stock AGNOS on the
             comma 3X is built with CONFIG_BT=n, so bluetooth_status() reports it unavailable.
"""
import glob
import os
import socket
import time

DEFAULT_WIFI = ("192.168.0.10", 35000)


class TransportError(OSError):
  pass


def bluetooth_status() -> tuple[bool, str]:
  """(usable, reason). Checks the kernel, not just Python: AF_BLUETOOTH exists in Python on most builds."""
  if not hasattr(socket, "AF_BLUETOOTH"):
    return False, "Python on this device has no Bluetooth socket support"
  try:
    adapters = os.listdir("/sys/class/bluetooth")
  except OSError:
    adapters = []
  if not adapters:
    return False, "this comma's operating system (AGNOS) is built without Bluetooth"
  try:
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    s.close()
  except OSError as e:
    return False, f"Bluetooth sockets fail: {e.strerror or e}"
  return True, f"adapter {adapters[0]}"


def usb_candidates() -> list[str]:
  return sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))


class Transport:
  kind = "none"

  def open(self) -> None: ...
  def close(self) -> None: ...
  def write(self, data: bytes) -> None: ...
  def read(self, timeout: float) -> bytes: ...

  def __enter__(self):
    self.open()
    return self

  def __exit__(self, *exc):
    self.close()


class _SocketTransport(Transport):
  def __init__(self):
    self.sock: socket.socket | None = None

  def _connect(self) -> socket.socket:
    raise NotImplementedError

  def open(self):
    try:
      self.sock = self._connect()
    except OSError as e:
      raise TransportError(f"{self.kind}: cannot connect: {e.strerror or e}") from None

  def close(self):
    if self.sock is not None:
      try:
        self.sock.close()
      finally:
        self.sock = None

  def write(self, data: bytes):
    if self.sock is None:
      raise TransportError("not open")
    try:
      self.sock.sendall(data)
    except OSError as e:
      raise TransportError(f"{self.kind}: write failed: {e.strerror or e}") from None

  def read(self, timeout: float) -> bytes:
    if self.sock is None:
      raise TransportError("not open")
    self.sock.settimeout(max(0.001, timeout))
    try:
      data = self.sock.recv(4096)
    except TimeoutError:
      return b""
    except OSError as e:
      raise TransportError(f"{self.kind}: read failed: {e.strerror or e}") from None
    if not data:
      raise TransportError(f"{self.kind}: adapter closed the connection")
    return data


class TcpTransport(_SocketTransport):
  kind = "wifi"

  def __init__(self, host: str = DEFAULT_WIFI[0], port: int = DEFAULT_WIFI[1], connect_timeout: float = 4.0):
    super().__init__()
    self.host, self.port, self.connect_timeout = host, port, connect_timeout

  def _connect(self):
    s = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s


class RfcommTransport(_SocketTransport):
  kind = "bluetooth"

  def __init__(self, mac: str, channel: int = 1):
    super().__init__()
    self.mac, self.channel = mac, channel

  def _connect(self):
    ok, why = bluetooth_status()
    if not ok:
      raise OSError(why)
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    s.settimeout(8.0)
    s.connect((self.mac, self.channel))
    return s


class SerialTransport(Transport):
  kind = "usb"

  def __init__(self, path: str, baud: int = 38400):
    self.path, self.baud = path, baud
    self.port = None

  def open(self):
    import serial  # pyserial ships with openpilot
    try:
      self.port = serial.Serial(self.path, self.baud, timeout=0)
    except (OSError, serial.SerialException) as e:
      raise TransportError(f"usb: cannot open {self.path}: {e}") from None

  def close(self):
    if self.port is not None:
      self.port.close()
      self.port = None

  def write(self, data: bytes):
    if self.port is None:
      raise TransportError("not open")
    self.port.write(data)

  def read(self, timeout: float) -> bytes:
    if self.port is None:
      raise TransportError("not open")
    end = time.monotonic() + timeout
    while True:
      data = self.port.read(4096)
      if data or time.monotonic() >= end:
        return data
      time.sleep(0.005)


def parse_wifi_address(address: str) -> tuple[str, int]:
  address = (address or "").strip()
  if not address:
    return DEFAULT_WIFI
  host, _, port = address.rpartition(":") if ":" in address else (address, "", "")
  return host, int(port) if port else DEFAULT_WIFI[1]


def make_transport(kind: str, address: str) -> Transport:
  kind = (kind or "").strip().lower()
  if kind == "wifi":
    return TcpTransport(*parse_wifi_address(address))
  if kind == "usb":
    path = address.strip() or next(iter(usb_candidates()), "")
    if not path:
      raise TransportError("usb: no USB serial adapter found")
    return SerialTransport(path)
  if kind == "bluetooth":
    mac, _, ch = address.strip().partition("#")
    if not mac:
      raise TransportError("bluetooth: no adapter address set")
    return RfcommTransport(mac, int(ch) if ch else 1)
  if kind == "simulated":
    from openpilot.selfdrive.car.obd.sim import SimTransport
    return SimTransport()
  raise TransportError(f"unknown OBD transport {kind!r}")
