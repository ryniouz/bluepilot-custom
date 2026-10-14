"""Best-effort push of drive events to the home server."""
import json
import threading
import urllib.request

from bluepilot.bridge.store import EventLog

PUSH_KINDS = ("drive_finished",)


class Notifier(threading.Thread):
  """Watches the event log and POSTs push-worthy events to BPBridgeNotifyUrl."""

  def __init__(self, events: EventLog, url_getter, token_getter, timeout_s: float = 5.0):
    super().__init__(daemon=True, name="bp_bridge_notify")
    self.events = events
    self.url_getter = url_getter
    self.token_getter = token_getter
    self.timeout_s = timeout_s
    self.stop_event = threading.Event()
    self.next_seq = events.next_seq

  def push(self, event: dict) -> bool:
    url = (self.url_getter() or "").strip()
    if not url.startswith(("http://", "https://")):
      return False
    req = urllib.request.Request(url, data=json.dumps({"event": event}).encode(), method="POST", headers={
      "Content-Type": "application/json", "Authorization": f"Bearer {self.token_getter()}",
    })
    try:
      with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
        return 200 <= resp.status < 300
    except Exception:
      return False

  def run(self) -> None:
    while not self.stop_event.is_set():
      for e in self.events.wait_for(self.next_seq, timeout=30.0):
        self.next_seq = e["seq"] + 1
        if e["kind"] in PUSH_KINDS:
          self.push(e)
