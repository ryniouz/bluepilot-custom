"""Connect > Wi-Fi and Connect backend: the pure rules behind the rows."""
from bluepilot.ui.lib import wifi_settings as ws


def test_signal_level_is_one_to_four_bars():
  assert [ws.signal_level(s) for s in (0, 1, 25, 26, 50, 51, 75, 76, 100, 140, -5)] == [1, 1, 1, 2, 2, 3, 3, 4, 4, 4, 1]


def test_network_status_priority():
  base = dict(connected=False, connecting=False, forgetting=False, saved=False, secured=True)
  assert ws.network_status(**base) == "Secured"
  assert ws.network_status(**{**base, "secured": False}) == "Open"
  assert ws.network_status(**{**base, "saved": True}) == "Saved"
  assert ws.network_status(**{**base, "saved": True, "connected": True}) == "Connected"
  assert ws.network_status(**{**base, "connected": True, "connecting": True}) == "Connecting…"
  assert ws.network_status(**{**base, "connected": True, "forgetting": True}) == "Forgetting…"
  assert ws.network_status(**base, supported=False) == "Security not supported"


def test_tap_action_matches_the_stock_panel():
  kw = dict(connected=False, saved=False, secured=True, supported=True, busy=False)
  assert ws.tap_action(**kw) == "password"                       # new secured network: ask first
  assert ws.tap_action(**{**kw, "secured": False}) == "connect"    # open network
  assert ws.tap_action(**{**kw, "saved": True}) == "connect"       # saved: no password needed
  assert ws.tap_action(**{**kw, "saved": True, "connected": True}) == "none"
  assert ws.tap_action(**{**kw, "supported": False}) == "none"
  assert ws.tap_action(**{**kw, "busy": True}) == "none"


def test_saved_ssids_drop_the_hotspot_and_sort():
  assert ws.saved_ssids(["weedle-1a2b", "home", "Cabin", "", "home"], "weedle-1a2b") == ["Cabin", "home"]


def test_preferred_choices():
  assert ws.preferred_choices(["Cabin", "home"], "") == (["None", "Cabin", "home"], 0)
  assert ws.preferred_choices(["Cabin", "home"], "home") == (["None", "Cabin", "home"], 2)
  # a favorite that isn't saved stays visible instead of silently showing "None"
  assert ws.preferred_choices([], "Shop") == (["None", "Shop"], 1)


def test_stale_favorite_only_once_connections_are_known():
  assert ws.stale_favorite("home", ["Cabin", "weedle"])
  assert not ws.stale_favorite("home", ["home"])
  assert not ws.stale_favorite("home", [])      # NetworkManager hasn't reported yet
  assert not ws.stale_favorite("", ["Cabin"])


def test_forwarding_follows_the_sim_plan():
  assert ws.forwarding_allowed(0) and ws.forwarding_allowed(2)          # NONE, LITE: the user's own SIM
  assert not any(ws.forwarding_allowed(t) for t in (-2, -1, 1, 3, 4, 5))


def test_backend_pending():
  assert ws.backend_pending("konik", "comma")
  assert not ws.backend_pending("comma", "comma")
  assert not ws.backend_pending("konik", None)
  assert not ws.backend_pending("konik", "")


def test_short_id_and_text():
  assert ws.short_id("1a2b3c4d5e6f7a8b") == "1a2b3c…7a8b"
  assert ws.short_id("abc") == "abc"
  assert ws.short_id(None) == ""
  assert ws.text(b"home\x00") == "home"
