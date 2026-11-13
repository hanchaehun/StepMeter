"""Prepare ten regression pairs and ten wording variants from pinned public builds.

Copies the production artifact without changing the checkout. Each version records
its base manifest and overlay hash. Confirmation gates add one required click;
wording changes preserve the control's role, handler and destination.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from benchmark.run_development import ROOT

OVERLAY = r'''(() => {
const config=CONFIG;
let released=null;
if(config.kind==='regression') {
 for(const kind of ['pointerdown','pointerup','mousedown','mouseup'])document.addEventListener(kind,e=>{
  const target=e.target.closest(config.selector);
  if(target && target!==released && !target.closest('[data-stepmeter-confirm]')){e.preventDefault();e.stopImmediatePropagation();}
 },true);
 document.addEventListener('click', e=>{
  const target=e.target.closest(config.selector);
  if(!target || target===released || target.closest('[data-stepmeter-confirm]'))return;
  e.preventDefault();e.stopImmediatePropagation();
  const dialog=document.createElement('dialog');dialog.dataset.stepmeterConfirm='true';
  dialog.setAttribute('aria-label','Confirm action');
  dialog.innerHTML='<p>Continue with this action?</p><button type="button">Continue</button><button type="button">Cancel</button>';
  dialog.querySelector('button').onclick=()=>{dialog.close();dialog.remove();released=target;try{
   target.focus();
   target.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,button:0,buttons:1,pointerType:'mouse',isPrimary:true}));
   target.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,button:0,buttons:1}));
   target.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,button:0,buttons:0,pointerType:'mouse',isPrimary:true}));
   target.dispatchEvent(new MouseEvent('mouseup',{bubbles:true,button:0,buttons:0}));
   target.click();
  }finally{released=null;}};
  dialog.querySelectorAll('button')[1].onclick=()=>{dialog.close();dialog.remove();};
  document.body.append(dialog);dialog.showModal();
 },true);
} else {
 const apply=()=>document.querySelectorAll(config.selector).forEach(el=>{
  if(el.dataset.stepmeterWording==='true')return;
  el.dataset.stepmeterWording='true';
  if(el.hasAttribute('aria-label'))el.setAttribute('aria-label',config.text);
  else if(el.matches('input'))el.setAttribute('placeholder',config.text);
  else {
   const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);
   let n;while((n=walker.nextNode()))if(n.textContent.trim()){n.textContent=config.text;return;}
   el.setAttribute('aria-label',config.text);
  }
 });
 new MutationObserver(apply).observe(document.documentElement,{childList:true,subtree:true});apply();
}
})();'''


def prepare(recipe, kind, destination):
    app=recipe['app_id']
    if app not in {'sb-admin-2','material-kit-react','react-shopping-cart','shadcn-admin'}:
        raise ValueError('Development apps only')
    source=ROOT/'builds'/app/'baseline'
    manifest=json.loads((source/'stepmeter-build.json').read_text(encoding='utf-8'))
    if manifest['app']!=app or manifest['variant']!='baseline':
        raise ValueError('Pinned baseline required')
    root=source if app=='sb-admin-2' else source/'dist'
    if destination.exists():raise ValueError('Existing evidence/build must not be overwritten')
    if app=='sb-admin-2':
        shutil.copytree(root,destination,ignore=shutil.ignore_patterns('.git','node_modules','stepmeter-build.json'))
    else:shutil.copytree(root,destination)
    config={**recipe,'kind':kind}
    overlay=OVERLAY.replace('CONFIG',json.dumps(config,ensure_ascii=False),1)
    (destination/'stepmeter-version.js').write_text(overlay,encoding='utf-8')
    pages=list(destination.glob('*.html'))
    for page in pages:
        text=page.read_text(encoding='utf-8')
        text=text.replace('</head>','<script defer src="/stepmeter-version.js"></script></head>')
        page.write_text(text,encoding='utf-8')
    result={'version':1,'id':recipe['id'],'kind':kind,'baseline':manifest,
            'overlay_sha256':hashlib.sha256(overlay.encode()).hexdigest(),
            'expected':{'additional_required_clicks':1} if kind=='regression' else {'same_behavior':True}}
    (destination/'version.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'builds/w3-versions')
    args=p.parse_args();recipes=json.loads((ROOT/'regression_cases.json').read_text(encoding='utf-8'))
    results=[]
    for kind in ('regression','wording'):
        for recipe in recipes['cases']:
            try:
                result=prepare(recipe,kind,args.output/kind/recipe['id']);result['status']='prepared'
            except (FileNotFoundError,ValueError) as error:
                result={'id':recipe['id'],'kind':kind,'status':'unavailable','reason':str(error)}
            results.append(result)
    args.output.mkdir(parents=True,exist_ok=True)
    with (args.output/'summary.json').open('x',encoding='utf-8') as f:json.dump(results,f,ensure_ascii=False,indent=2)
    print(json.dumps(results,ensure_ascii=False,indent=2))
    raise SystemExit(0 if all(r['status']=='prepared' for r in results) else 2)


if __name__=='__main__':main()
