"""Prepare an isolated pinned development app with baseline + one source patch.

Never reset or edit the author's checkout. Builds are git-ignored. React source
patches survive rerenders; DOM mutation tools remain only for static fixtures.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from benchmark.serve_variants import resolve_command

ROOT =Path(__file__).resolve().parent
VARIANTS = ('baseline', 'small', 'contrast', 'inert', 'overlay', 'below-fold', 'unnamed')


def prepare(app: dict, variant: str, source: Path, destination: Path) -> dict:
    if app['split'] != 'development':
        raise ValueError('public builder accepts development apps only')
    if variant not in VARIANTS or destination.exists():
        raise ValueError('unknown variant or destination already exists; preserve existing builds')
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', app['revision'] + '^{commit}'], text=True).strip()
    if revision != app['revision']:
        raise ValueError('pinned revision mismatch')
    patches = [ROOT / 'baselines' / f"{app['id']}.patch"]
    if not patches[0].is_file():
        raise ValueError('baseline patch is required before variant preparation')
    if variant != 'baseline':
        patches.append(ROOT / 'mutations' / app['id'] / f'{variant}.patch')
        if not patches[-1].is_file():
            raise ValueError('source mutation patch is not available')
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'clone', '--no-hardlinks', '--no-checkout', str(source.resolve()), str(destination)], check=True)
    subprocess.run(['git', '-C', str(destination), 'checkout', '--detach', revision], check=True)
    provenance = []
    for patch in patches:
        subprocess.run(['git', '-C', str(destination), 'apply', '--check', str(patch)], check=True)
        subprocess.run(['git', '-C', str(destination), 'apply', str(patch)], check=True)
        provenance.append({'path': patch.relative_to(ROOT).as_posix(),'sha256': hashlib.sha256(patch.read_bytes()).hexdigest()})
    result = {'app': app['id'], 'variant': variant, 'revision': revision, 'patches': provenance}
    (destination / 'stepmeter-build.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    apps = {a['id']: a for a in json.loads((ROOT / 'apps.json').read_text(encoding='utf-8'))['apps'] if a['split'] == 'development'}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', choices=sorted(apps))
    parser.add_argument('variant', choices=VARIANTS)
    parser.add_argument('--build', action='store_true', help='Install pinned dependencies and build React app')
    args = parser.parse_args()
    app = apps[args.app]
    source = ROOT / 'apps' / args.app
    destination = ROOT / 'builds' / args.app / args.variant
    result = prepare(app, args.variant, source, destination)
    if args.build:
        commands = {
            'shadcn-admin': [['npx', '--yes', 'pnpm@9.15.9', 'install', '--frozen-lockfile'],
                             ['npx', '--yes', 'pnpm@9.15.9', 'exec', 'vite', 'build']],
            'material-kit-react': [['npm', 'ci'], ['npm', 'run', 'build']],
            'sb-admin-2': [],
            'react-shopping-cart': [['npm', 'ci'], ['npm', 'run', 'build']],
        }[args.app]
        for command in commands:
            # Windows의 npm·npx는 .cmd라 이름만으로는 실행되지 않는다 (serve_variants와 같은 방식)
            subprocess.run(resolve_command(command), cwd=destination, check=True)
    print(json.dumps(result))
    print(f'Prepared: {destination}')


if __name__ == '__main__':
    main()
