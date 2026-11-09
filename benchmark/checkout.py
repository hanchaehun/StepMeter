"""Fetch pinned source apps without placing nested repositories in the index."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), *args], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apps", nargs="*", help="Default: development apps only")
    parser.add_argument("--include-holdout", action="store_true")
    args = parser.parse_args()
    apps = json.loads((ROOT / "apps.json").read_text(encoding="utf-8"))["apps"]
    holdout = ROOT / "holdout" / "apps.json"
    if args.include_holdout and holdout.exists():
        apps += [
            app for app in json.loads(holdout.read_text(encoding="utf-8"))["apps"]
            if app["split"] == "holdout"
        ]
    known = {app["id"] for app in apps}
    if set(args.apps) - known:
        parser.error("Unknown app id")
    selected = [app for app in apps if app["id"] in args.apps] if args.apps else [
        app for app in apps if app["split"] == "development"
    ]
    if any(app["split"] == "holdout" for app in selected) and not args.include_holdout:
        parser.error("Holdout checkout requires --include-holdout; do not share labels/configs")
    for app in selected:
        path = ROOT / "apps" / app["id"]
        if path.exists():
            raise SystemExit(f"Already exists: {path}. Preserve local changes; use another checkout.")
        path.mkdir(parents=True)
        git(path, "init", "-q")
        git(path, "remote", "add", "origin", app["repository"] + ".git")
        git(path, "fetch", "--depth", "1", "origin", app["revision"])
        git(path, "checkout", "--detach", "FETCH_HEAD")
        patch_root = ROOT / "holdout" if app["split"] == "holdout" else ROOT
        patch = patch_root / "baselines" / (app["id"] + ".patch")
        if patch.exists():
            git(path, "apply", "--check", str(patch))
            git(path, "apply", str(patch))
        print(f"Ready: {app['id']} at {app['revision']}")


if __name__ == "__main__":
    main()
