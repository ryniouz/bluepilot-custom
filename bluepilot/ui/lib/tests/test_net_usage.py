"""Connect > Cellular's month view: units, the per-category breakdown and the reset date."""
import datetime as dt

from bluepilot.ui.lib.net_usage import fmt_data, month_breakdown, next_reset


def test_fmt_data_uses_mb_and_gb():
  assert fmt_data(0) == "0 MB"
  assert fmt_data(-5) == "0 MB"
  assert fmt_data(2_340_000) == "2.3 MB"
  assert fmt_data(412_000_000) == "412 MB"
  assert fmt_data(1_420_000_000) == "1.42 GB"
  assert fmt_data(12_500_000_000) == "12.5 GB"


def test_no_bridge_means_no_breakdown():
  assert month_breakdown(None, 5000) == (5000, None)
  assert month_breakdown({"limitBytes": 0}, 7) == (7, None)


def test_breakdown_from_the_bridge():
  usage = {"cell": {"monthBytes": 1000}, "categories": {"citadel": 400, "commaConnect": 100, "live": 50, "link": 25,
                                                         "other": 425}}
  month, cats = month_breakdown(usage, 99)
  assert month == 1000
  assert cats == {"citadel": 400, "commaConnect": 100, "live": 50, "link": 25, "other": 425}


def test_breakdown_never_exceeds_the_month_and_other_is_never_negative():
  usage = {"cell": {"monthBytes": 300}, "categories": {"citadel": 250, "commaConnect": 200, "live": -3}}
  _, cats = month_breakdown(usage, 0)
  assert cats == {"citadel": 250, "commaConnect": 50, "live": 0, "link": 0, "other": 0}


def test_older_bridge_still_knows_its_own_uploads():
  usage = {"cell": {"monthBytes": 900}, "uploader": {"cellBytesMonth": 600}}
  assert month_breakdown(usage, 0) == (900, {"citadel": 600, "commaConnect": 0, "live": 0, "link": 0, "other": 300})


def test_next_reset():
  assert next_reset(dt.date(2026, 10, 14), 1) == dt.date(2026, 11, 1)
  assert next_reset(dt.date(2026, 10, 14), 20) == dt.date(2026, 10, 20)
  assert next_reset(dt.date(2026, 10, 20), 20) == dt.date(2026, 11, 20)
  assert next_reset(dt.date(2026, 1, 31), 31) == dt.date(2026, 2, 28)
  assert next_reset(dt.date(2026, 12, 5), 1) == dt.date(2027, 1, 1)
