"""Where the month's cellular data went: per-category counters, the comma connect meter and `other`."""
import datetime as dt

from bluepilot.bridge import meter
from bluepilot.bridge.usage import CATEGORIES, DataUsage, breakdown


def make(tmp_path, day):
  return DataUsage(str(tmp_path / "usage.json"), today=lambda: day[0])


def test_breakdown_other_is_the_rest_and_never_negative():
  assert breakdown(1000, {"citadel": 300, "live": 50}) == {"commaConnect": 0, "citadel": 300, "live": 50, "link": 0,
                                                          "other": 650}
  # categories can't add up to more than the modem counted (metered Wi-Fi uploads never reach the modem)
  b = breakdown(100, {"commaConnect": 80, "citadel": 80})
  assert b == {"commaConnect": 80, "citadel": 20, "live": 0, "link": 0, "other": 0}
  assert breakdown(0, {}) == {**dict.fromkeys(CATEGORIES, 0), "other": 0}
  assert breakdown(50, {"citadel": -5})["other"] == 50


def test_uploads_count_by_category_on_cellular_only(tmp_path):
  day = [dt.date(2026, 10, 14)]
  u = make(tmp_path, day)
  u.observe_modem(0, 0)
  u.observe_modem(5000, 5000)
  u.add_upload(1000, cellular=True)                  # Citadel segment upload (the default)
  u.add_upload(200, cellular=True, category="live")
  u.add_upload(30, cellular=True, category="link")
  u.add_upload(9999, cellular=False, category="live")  # Wi-Fi: not cellular data
  c = u.summary()["categories"]
  assert c == {"commaConnect": 0, "citadel": 1000, "live": 200, "link": 30, "other": 10000 - 1230}
  assert u.summary()["uploader"]["cellBytesMonth"] == 1230  # unchanged meaning for older readers


def test_comma_meter_deltas_restarts_and_month_reset(tmp_path):
  day = [dt.date(2026, 10, 14)]
  u = make(tmp_path, day)
  u.observe_modem(0, 0)
  u.observe_modem(10_000, 0)
  u.observe_comma(400)        # first reading after start: baseline only
  u.observe_comma(1400)
  u.observe_comma(None)       # meter not there (uploader never sent over LTE this boot)
  u.observe_comma(300)        # reboot: the tmpfs meter starts from zero
  assert u.summary()["categories"]["commaConnect"] == 1300
  day[0] = dt.date(2026, 11, 1)
  assert u.summary()["categories"] == {**dict.fromkeys(CATEGORIES, 0), "other": 0}


def test_categories_persist_with_the_month(tmp_path):
  day = [dt.date(2026, 10, 14)]
  u = make(tmp_path, day)
  u.observe_modem(0, 0)
  u.observe_modem(2_000_000, 0)
  u.add_upload(700, cellular=True, category="link")
  u.save()
  u2 = make(tmp_path, day)
  assert u2.summary()["categories"]["link"] == 700
  day[0] = dt.date(2026, 11, 2)
  u3 = make(tmp_path, day)
  assert u3.summary()["categories"]["link"] == 0


def test_meter_file(tmp_path):
  path = str(tmp_path / "m")
  assert meter.read(path) is None
  meter.add(0, path)
  assert meter.read(path) is None
  meter.add(1200, path)
  meter.add(34, path)
  assert meter.read(path) == 1234
  meter.add(5, str(tmp_path / "missing" / "m"))  # never raises
