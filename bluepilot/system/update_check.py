"""
Update checks for System > Updates, beside the stock updater (system/updated/updated.py):

  Lucas's fork      BPUpdateRepo at the update branch: its newest commit and that commit's CITADEL_VERSION.
                    This is the only source the comma installs from (updated.py downloads it).
  BluePilot         upstream BluePilotDev/openpilot: the newest release branch (bp-X.Y) and its BPVERSION, and
                    how many commits bp-dev has past the commit this build is based on. Shown and marked only:
                    a BluePilot release reaches the comma after it is built into the fork.

Results land in the BPForkStatus and BPUpstreamStatus params (JSON). updated.py runs check_all() on every
check; the Updates page runs it too when you tap Check, so the page fills in without updated (on a PC).
Nothing here downloads or installs anything.
"""

from __future__ import annotations

import json
import re
import subprocess
import datetime
import urllib.request

from bluepilot.ui.lib.versions import UPSTREAM_BASE_BRANCH, UPSTREAM_BASE_COMMIT, UPSTREAM_REPO, citadel_version, newer, versions

DEFAULT_FORK = "https://github.com/ryniouz/bluepilot-custom.git"
TIMEOUT_S = 20
RELEASE_RE = re.compile(r"bp-(\d+)\.(\d+)")


def _text(v) -> str:
  if isinstance(v, bytes):
    v = v.decode(errors="ignore")
  return str(v or "").strip("\x00").strip()


def github_path(url: str) -> str:
  """'https://github.com/ryniouz/bluepilot-custom.git' -> 'ryniouz/bluepilot-custom'; '' for other hosts."""
  m = re.match(r"https://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", url.strip())
  return m.group(1) if m else ""


def ls_remote(url: str, *refs: str) -> dict[str, str]:
  """{ref name without refs/heads/: commit} for the remote's branches (all of them, or just `refs`)."""
  out = subprocess.check_output(["git", "ls-remote", "--heads", url, *refs], timeout=TIMEOUT_S, text=True,
                                stderr=subprocess.DEVNULL)
  heads = {}
  for line in out.splitlines():
    parts = line.split()
    if len(parts) == 2 and parts[1].startswith("refs/heads/"):
      heads[parts[1].removeprefix("refs/heads/")] = parts[0]
  return heads


def fetch_text(url: str) -> str:
  req = urllib.request.Request(url, headers={"User-Agent": "citadel-auto-os"})
  with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
    return r.read(64 * 1024).decode(errors="ignore").strip()


def raw_file(repo_url: str, ref: str, path: str) -> str:
  gh = github_path(repo_url)
  return fetch_text(f"https://raw.githubusercontent.com/{gh}/{ref}/{path}") if gh else ""


def newest_release(heads: dict[str, str]) -> str:
  """The highest bp-X.Y branch name ('' when there is none)."""
  best, best_v = "", (-1, -1)
  for name in heads:
    m = RELEASE_RE.fullmatch(name)
    if m and (int(m.group(1)), int(m.group(2))) > best_v:
      best, best_v = name, (int(m.group(1)), int(m.group(2)))
  return best


# -- checks -----------------------------------------------------------------------------------------

def check_fork(params) -> dict:
  repo = _text(params.get("BPUpdateRepo")) or DEFAULT_FORK
  branch = _text(params.get("BPUpdateBranch")) or _text(params.get("UpdaterTargetBranch")) or _text(params.get("GitBranch"))
  installed = _text(params.get("GitCommit"))
  status: dict = {"checkedAt": int(datetime.datetime.now().timestamp()), "repo": github_path(repo) or repo, "branch": branch,
                  "installedCommit": installed[:7], "installedVersion": citadel_version()}
  try:
    if not branch:
      raise ValueError("no update branch yet")
    commit = ls_remote(repo, branch).get(branch, "")
    if not commit:
      raise ValueError(f"branch {branch} not found")
    try:
      version = raw_file(repo, commit, "CITADEL_VERSION")
    except Exception:
      version = ""
    status.update(commit=commit[:7], version=version,
                  available=bool(installed) and not commit.startswith(installed[:7]),
                  newerVersion=newer(version, citadel_version()))
  except Exception as e:
    status["error"] = str(e)[:200]
  params.put("BPForkStatus", status)
  return status


def check_upstream(params) -> dict:
  installed = versions().bluepilot
  status: dict = {"checkedAt": int(datetime.datetime.now().timestamp()), "repo": github_path(UPSTREAM_REPO), "installedVersion": installed,
                  "baseBranch": UPSTREAM_BASE_BRANCH, "baseCommit": UPSTREAM_BASE_COMMIT[:7]}
  try:
    heads = ls_remote(UPSTREAM_REPO)
    release = newest_release(heads)
    if release:
      try:
        rel_version = raw_file(UPSTREAM_REPO, heads[release], "BPVERSION")
      except Exception:
        rel_version = ""
      status["release"] = {"branch": release, "commit": heads[release][:7], "version": rel_version}
      status["available"] = newer(rel_version, installed) or (not rel_version and newer(release.removeprefix("bp-"), installed))
    dev = heads.get(UPSTREAM_BASE_BRANCH, "")
    if dev:
      ahead = 0
      if not dev.startswith(UPSTREAM_BASE_COMMIT[:7]):
        try:
          gh = github_path(UPSTREAM_REPO)
          cmp = json.loads(fetch_text(f"https://api.github.com/repos/{gh}/compare/{UPSTREAM_BASE_COMMIT}...{dev}"))
          ahead = int(cmp.get("ahead_by", 0))
        except Exception:
          ahead = -1   # moved, count unknown
      status["dev"] = {"branch": UPSTREAM_BASE_BRANCH, "commit": dev[:7], "ahead": ahead}
  except Exception as e:
    status["error"] = str(e)[:200]
  params.put("BPUpstreamStatus", status)
  return status


def check_all(params) -> None:
  for fn in (check_fork, check_upstream):
    try:
      fn(params)
    except Exception:
      pass
