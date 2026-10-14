"""Deleter keep-until-synced behaviour, with the openpilot runtime stubbed out."""
import importlib.util
import os
import sys
import threading
import types

import pytest

from bluepilot.bridge.params_allowlist import coerce_param
from bluepilot.bridge.store import SyncedStore

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
GB = 1024 ** 3


def load_deleter(monkeypatch, log_root, free, keep=True):
  """Import system/loggerd/deleter.py with stub modules; `free` is a dict {bytes, percent} we can mutate."""
  def stub(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    monkeypatch.setitem(sys.modules, name, m)

  class Paths:
    @staticmethod
    def log_root():
      return str(log_root)

    @staticmethod
    def log_root_external():
      return "/nonexistent-external"

  class Params:
    def get_bool(self, key):
      return keep

  stub("openpilot.system.hardware.hw", Paths=Paths)
  stub("openpilot.common.swaglog", cloudlog=types.SimpleNamespace(info=lambda *a: None, warning=lambda *a: None,
                                                                   error=lambda *a: None, exception=lambda *a: None))
  stub("openpilot.system.loggerd.config", get_available_bytes=lambda default=None, path_type=None: free["bytes"],
       get_available_percent=lambda default=None, path_type=None: free["percent"])
  stub("openpilot.system.loggerd.uploader", listdir_by_creation=lambda d: sorted(os.listdir(d)))
  stub("openpilot.system.loggerd.xattr_cache", getxattr=lambda *a: None)
  stub("openpilot.common.params", Params=Params)
  spec = importlib.util.spec_from_file_location("deleter_under_test", os.path.join(REPO, "system/loggerd/deleter.py"))
  mod = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(mod)
  return mod


def run_once(mod):
  """Run the deleter loop until it either deletes something or goes idle once."""
  ev = threading.Event()
  orig_wait = ev.wait
  calls = []

  def wait(t):
    calls.append(t)
    ev.set()
    return orig_wait(0)

  ev.wait = wait
  mod.deleter_thread(ev)
  return calls


@pytest.fixture
def setup(tmp_path, monkeypatch):
  root = tmp_path / "realdata"
  state = tmp_path / "state"
  for name in ["00000001--aaaa--0", "00000001--aaaa--1", "00000002--bbbb--0"]:
    (root / name).mkdir(parents=True)
    (root / name / "rlog.zst").write_bytes(b"x")
  monkeypatch.setenv("BP_BRIDGE_STATE_DIR", str(state))
  import bluepilot.bridge.config as config_mod
  monkeypatch.setattr(config_mod, "STATE_DIR", str(state))
  return root, state


def test_synced_deleted_before_older_unsynced(setup, monkeypatch):
  root, state = setup
  SyncedStore(str(state)).mark(["00000002--bbbb--0"], "logs")
  free = {"bytes": 4 * GB, "percent": 8}  # below normal threshold, above hard floor
  mod = load_deleter(monkeypatch, root, free)
  run_once(mod)
  assert sorted(os.listdir(root)) == ["00000001--aaaa--0", "00000001--aaaa--1"]


def test_unsynced_kept_until_hard_floor(setup, monkeypatch):
  root, _ = setup
  free = {"bytes": 4 * GB, "percent": 8}
  mod = load_deleter(monkeypatch, root, free)
  calls = run_once(mod)
  assert len(os.listdir(root)) == 3 and calls == [5]  # idles instead of spinning
  free.update(bytes=1 * GB, percent=3)
  run_once(mod)
  assert sorted(os.listdir(root)) == ["00000001--aaaa--1", "00000002--bbbb--0"]  # oldest goes first


def test_disabled_keeps_stock_order(setup, monkeypatch):
  root, _ = setup
  mod = load_deleter(monkeypatch, root, {"bytes": 4 * GB, "percent": 8}, keep=False)
  run_once(mod)
  assert sorted(os.listdir(root)) == ["00000001--aaaa--1", "00000002--bbbb--0"]


def test_coerce_param():
  assert coerce_param("true", False) is True and coerce_param(0, True) is False
  assert coerce_param("2", 1) == 2 and coerce_param(2.5, 3.0) == 2.5 and coerce_param(5, None) == "5"
  with pytest.raises(ValueError):
    coerce_param("maybe", False)
