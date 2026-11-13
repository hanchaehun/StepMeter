"""Generate a reviewable Vercel configuration for the confirmed Railway API URL.

Does not deploy, modify the repository config, or handle secrets.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[2]


def configuration(api_url):
    url=urlsplit(api_url)
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('','/'):
        raise ValueError('API must be an HTTPS origin without credentials, path or query')
    config=json.loads((ROOT/'vercel.json').read_text(encoding='utf-8'))
    config['rewrites']=[{'source':'/api/:path*','destination':api_url.rstrip('/')+'/:path*'},
                        *[r for r in config['rewrites'] if r['source']!='/api/:path*']]
    return config


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--api-url',required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    config=configuration(args.api_url)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as f:json.dump(config,f,indent=2)
    print(args.output)


if __name__=='__main__':main()
