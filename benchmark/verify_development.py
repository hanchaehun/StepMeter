"""Development-only build/render orchestration. Never loads holdout configuration."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from benchmark.build_variant import ROOT, VARIANTS

VERIFIERS = {'sb-admin-2': 'benchmark.verify_sb_admin',
             'material-kit-react': 'benchmark.verify_material_kit',
             'react-shopping-cart': 'benchmark.verify_shopping_cart'}


def main():
    manifest = json.loads((ROOT / 'apps.json').read_text(encoding='utf-8'))
    apps = {a['id']: a for a in manifest['apps'] if a['split'] == 'development'}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', action='store_true', help='Fetch missing pinned sources and build missing variants')
    args = parser.parse_args()
    results = []
    failed = False
    for name, app in apps.items():
        patches = [ROOT / 'baselines' / f'{name}.patch'] + [ROOT / 'mutations' / name / f'{v}.patch' for v in VARIANTS if v != 'baseline']
        if any(not p.exists() for p in patches) or name not in VERIFIERS:
            results.append({'app': name, 'status': 'waiting_for_verifier_integration'
                            if all(p.exists() for p in patches) else 'waiting_for_source_submission'})
            continue
        try:
            source = ROOT / 'apps' / name
            if not source.exists() and args.build:
                subprocess.run([sys.executable, str(ROOT / 'checkout.py'), name], check=True)
            for variant in VARIANTS:
                destination = ROOT / 'builds' / name / variant
                if not destination.exists() and args.build:
                    command = [sys.executable, '-m', 'benchmark.build_variant', name, variant]
                    if name != 'sb-admin-2':
                        command.append('--build')
                    subprocess.run(command, check=True)
                provenance = json.loads((destination / 'stepmeter-build.json').read_text(encoding='utf-8'))
                assert provenance['revision'] == app['revision'], 'stale source revision'
                for patch in provenance['patches']:
                    digest = hashlib.sha256((ROOT / patch['path']).read_bytes()).hexdigest()
                    assert digest == patch['sha256'], 'stale build patch; preserve old build and prepare a new one'
            subprocess.run([sys.executable, '-m', VERIFIERS[name]], check=True)
            label = json.loads((ROOT / 'labels' / f'{name}.json').read_text(encoding='utf-8'))
            results.append({'app': name, 'status': 'render_verified',
                            'label_review': label['review_status'], 'source_mutations': 6})
        except (AssertionError, OSError, ValueError, subprocess.CalledProcessError) as error:
            failed = True
            results.append({'app': name, 'status': 'failed', 'error': str(error)})
    output = ROOT / 'evidence/development'
    output.mkdir(parents=True, exist_ok=True)
    report = {'scope': 'development build/render verification; not detector accuracy or agent E2E',
              'apps': results, 'holdout': 'excluded; no private manifest read'}
    (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
