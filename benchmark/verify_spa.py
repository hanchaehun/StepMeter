"""Run the synthetic SPA harness with an ephemeral loopback fixture server."""
from __future__ import annotations

import argparse
import asyncio
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread

from benchmark.spa_eval import ROOT, run_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/spa/synthetic")
    parser.add_argument("--chromium-executable")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "benchmark/spa/synthetic.json").read_text(encoding="utf-8"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(ROOT)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        report = asyncio.run(run_manifest(manifest, f"http://127.0.0.1:{server.server_port}", args.output,
                                          args.chromium_executable))
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    # Pending human review is intentionally not a certified pass.
    return 0 if report["summary"]["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
