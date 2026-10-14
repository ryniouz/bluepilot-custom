"""Custom: OBD adapter link tests (stream B)."""
import socket
import threading

import pytest

from openpilot.common.params import Params
from openpilot.selfdrive.car.obd import obdd
from openpilot.selfdrive.car.obd.catalog import BUILTIN, check_request, load_csv
from openpilot.selfdrive.car.obd.elm327 import Elm327, Negative, NoData, parse_lines, reassemble
from openpilot.selfdrive.car.obd.formula import Formula, FormulaError
from openpilot.selfdrive.car.obd.sim import SIM_RESPONSES, SimTransport, iso_tp_lines
from openpilot.selfdrive.car.obd.transports import TcpTransport, TransportError

KEYS = ("BPObdEnabled", "BPObdTransport", "BPObdAddress", "BPObdPollWhenOff", "IsOnroad", "BPChargingActive")


class TestFormula:
  def test_dialect(self):
    assert Formula("INT16(A,B)*0.002")(bytes([0x71, 0x48])) == pytest.approx(58.0)
    assert Formula("((SIGNED(A)*256)+B)*0.02")(bytes([0xFC, 0x18])) == pytest.approx(-20.0)
    assert Formula("((signed(A)*256)+B)/327.67")(bytes([0x80, 0])) == pytest.approx(-100.0, abs=0.01)
    f = Formula("if(A=6;1;if(A=8;1;0))")
    assert [f(bytes([x])) for x in (6, 7, 8)] == [1., 0., 1.]
    assert Formula("A/20+6")(b"") == 6.0  # missing bytes read as 0

  @pytest.mark.parametrize("bad", ["__import__('os')", "A.real", "open('x')", "[A]", "lambda: 1", "Z+1", "A if B else C"])
  def test_rejects_code(self, bad):
    with pytest.raises(FormulaError):
      Formula(bad)


class TestCatalog:
  @pytest.mark.parametrize("req", ["2E1234AA", "3101FF00", "2701", "1003", "1101", "14FFFFFF", "85", "XYZ1"])
  def test_only_reads(self, req):
    with pytest.raises(ValueError):
      check_request(req)

  def test_builtin_is_read_only_and_metric(self):
    assert all(p.service in (0x01, 0x09, 0x22) for p in BUILTIN)
    assert not any(p.unit.lower() in ("psi", "fahrenheit", "fahrengheit") for p in BUILTIN)

  def test_csv(self, tmp_path):
    path = tmp_path / "pids.csv"
    path.write_text("\n".join([
      'request,ecu_header,name,short_name,formula,byte_start,byte_len,mul,div,ofs,signed,bit,unit,role,min,max',
      '224800,7E4,HVB Temperature,HvbT,(A-50)*1.8+32,0,1,1,1,0,false,0,fahrengheit,,-50,400',
      '224808,7E4,Temp Max,TMax,(A-50)*1.8+32,0,1,1,1,0,false,0,fahrengheit,,0,0',
      '224808,7E4,Temp Min,TMin,(B-50)*1.8+32,0,1,1,1,0,false,0,fahrengheit,,0,0',
      '22DD01,7E0,Odometer,Odo,,0,3,1,0,0,false,1,km,,0,1000000',
      '2248F9,7E4,HVB Current,HvbA,,0,2,0.1,1,0,true,0,A,,-600,600',
      '2E0101,7E4,Write attempt,Bad,A,0,1,1,1,0,false,0,,,0,0',
      '224801,(default),SOC,Soc,"INT16(A,B)*0.002",0,1,1,1,0,false,0,percent,,0,100',
    ]) + "\n")
    pids, problems = load_csv(str(path))
    by = {(p.header, p.request): p for p in pids}
    assert len(problems) == 1 and "not a read" in problems[0]
    assert by[("7E4", "224800")].decode(bytes([77])) == pytest.approx(27.0)
    assert by[("7E4", "224800")].unit == "degC"
    temps = by[("7E4", "224808")]
    assert temps.short_name == "TMax" and temps.extra[0][0] == "TMin"
    assert by[("7E0", "22DD01")].decode(bytes([0x01, 0x86, 0xA0])) == 100000  # all 3 bytes, div 0 = 1
    assert by[("7E4", "2248F9")].decode(bytes([0xFF, 0x9B])) == pytest.approx(-10.1)  # signed
    assert ("7DF", "224801") in by  # "(default)" header = functional request


class TestElm:
  def test_single_and_multi_frame(self):
    payload = bytes([0x62, 0xF5, 0x07]) + bytes(range(40, 52))
    lines = iso_tp_lines(0x7EC, payload)
    assert len(lines) == 3
    assert reassemble(parse_lines("\r".join(lines)), 0x7EC) == payload
    assert reassemble(parse_lines("7EC 03 62 48 45 74"), 0x7EC) == bytes([0x62, 0x48, 0x45])
    assert reassemble(parse_lines("SEARCHING...\rNO DATA"), 0x7EC) is None

  def test_requests(self):
    t = SimTransport(responses={("7E4", "224801"): bytes.fromhex("7148"), ("7E4", "22F507"): bytes(range(20))})
    with t:
      elm = Elm327(t)
      elm.initialize()
      assert "ELM327" in elm.version and "CAN" in elm.protocol
      assert elm.request("7E4", "224801") == bytes.fromhex("7148")
      assert elm.request("7E4", "22F507") == bytes(range(20))  # multi-frame
      with pytest.raises(NoData):
        elm.request("7E4", "229999")
      with pytest.raises(ValueError):
        elm.request("7E4", "2E0101")  # never sent
    assert "2E0101" not in t.sent
    assert t.sent.count("ATSH7E4") == 1  # header switch only when it changes

  def test_functional_request(self):
    t = SimTransport(responses={})
    t._answer = lambda cmd: "OK" if cmd.startswith("AT") else "7EC037F2231\r7EA0562485E5DC0"
    with t:
      assert Elm327(t).request("7DF", "22485E") == bytes.fromhex("5DC0")  # 7EC refuses, 7EA answers

  def test_negative(self):
    t = SimTransport(responses={})
    t._answer = lambda cmd: "OK" if cmd.startswith("AT") else "7EC037F2231"
    with t:
      elm = Elm327(t)
      with pytest.raises(Negative) as e:
        elm.request("7E4", "224801")
      assert e.value.nrc == 0x31


@pytest.fixture
def params():
  p = Params()
  for k in KEYS:
    p.remove(k)
  return p


def service(params, sim=None, **kw):
  sim = sim or SimTransport()
  factory = kw.pop("factory", lambda kind, addr: sim)
  return obdd.ObdService(params, transport_factory=factory, catalog=list(BUILTIN), catalog_desc="built-in"), sim


class Clock:
  def __init__(self):
    self.t = 0.

  def __call__(self):
    self.t += 0.01  # every clock read costs 10 ms of budget
    return self.t


class TestService:
  def run(self, svc, seconds, start=100.):
    msg = None
    for i in range(int(seconds)):
      msg = svc.step(start + i, clock=Clock()).obdStateBP
    return msg

  def test_off_by_default(self, params):
    svc, sim = service(params)
    m = self.run(svc, 3)
    assert not m.enabled and m.link == "off" and not sim.sent

  def test_reads_values_while_onroad(self, params):
    params.put_bool("BPObdEnabled", True)
    params.put("BPObdTransport", "simulated")
    params.put_bool("IsOnroad", True)
    svc, sim = service(params)
    m = self.run(svc, 12)
    assert m.link == "connected" and m.polling and m.transport == "simulated"
    assert "ELM327" in m.adapter
    vals = {v.shortName: v for v in m.values}
    assert vals["HvbSoc"].value == pytest.approx(58.0) and vals["HvbSoc"].unit == "percent"
    assert vals["HvbT"].value == pytest.approx(27.0, abs=0.01) and vals["HvbT"].unit == "degC"
    assert vals["TireLF"].unit == "kPa" and 200 < vals["TireLF"].value < 320
    assert vals["HvbA"].value == pytest.approx(-20.0)
    assert vals["HvbSoh"].value == pytest.approx(97.0) and vals["HvbCHP"].value == pytest.approx(2.7)
    assert vals["ACInV"].value == pytest.approx(240.0) and vals["ACInA"].value == 47  # functional 7DF, answered on 7EA
    assert len(vals) == len(SIM_RESPONSES)
    assert m.requestsPerSecond > 0 and 0 <= m.lastResponseAgeS < 2
    # only reads ever reach the adapter
    assert all(c.startswith("AT") or c[:2] in ("01", "09", "22") for c in sim.sent)

  def test_paused_when_truck_off(self, params):
    params.put_bool("BPObdEnabled", True)
    params.put("BPObdTransport", "simulated")
    svc, sim = service(params)
    m = self.run(svc, 4)
    assert m.link == "idle" and not m.polling and not sim.sent
    params.put_bool("BPChargingActive", True)  # charging counts as awake
    m = self.run(svc, 4, start=200.)
    assert m.link == "connected" and m.values

  def test_car_asleep(self, params):
    params.put_bool("BPObdEnabled", True)
    params.put("BPObdTransport", "simulated")
    params.put_bool("BPObdPollWhenOff", True)
    svc, sim = service(params, sim=SimTransport(asleep=True))
    m = self.run(svc, 5)
    assert m.link == "carAsleep" and not m.values

  def test_bluetooth_unavailable(self, params):
    params.put_bool("BPObdEnabled", True)
    params.put("BPObdTransport", "bluetooth")
    params.put_bool("IsOnroad", True)
    svc, sim = service(params)
    svc.bt_ok, svc.bt_msg = False, "this comma's operating system (AGNOS) is built without Bluetooth"
    m = self.run(svc, 3)
    assert m.link == "unavailable" and "AGNOS" in m.message and not m.bluetoothAvailable and not sim.sent

  def test_connect_failure_backs_off(self, params):
    params.put_bool("BPObdEnabled", True)
    params.put("BPObdTransport", "wifi")
    params.put_bool("IsOnroad", True)
    attempts = []

    def factory(kind, addr):
      attempts.append(kind)
      raise TransportError("wifi: cannot connect: Connection refused")
    svc, _ = service(params, factory=factory)
    m = self.run(svc, 12)
    assert m.link == "error" and "retrying" in m.message
    assert len(attempts) == 2  # t=0 and t=+5 s, then 10 s backoff


def test_tcp_end_to_end():
  """A real TCP socket in front of the simulated adapter, as with a Wi-Fi dongle or a Bluetooth bridge."""
  srv = socket.socket()
  srv.bind(("127.0.0.1", 0))
  srv.listen(1)
  port = srv.getsockname()[1]

  def serve():
    conn, _ = srv.accept()
    sim = SimTransport()
    sim.open()
    buf = b""
    with conn:
      while True:
        data = conn.recv(1024)
        if not data:
          return
        buf += data
        while b"\r" in buf:
          line, buf = buf.split(b"\r", 1)
          sim.write(line + b"\r")
          conn.sendall(sim.read(0.1))
  th = threading.Thread(target=serve, daemon=True)
  th.start()
  with TcpTransport("127.0.0.1", port) as t:
    elm = Elm327(t)
    elm.initialize()
    assert elm.request("7E4", "224801") == bytes.fromhex("7148")
  srv.close()
