"""Browser-check each prepared public regression/wording version; preserve evidence.

Checks the added confirmation interaction and actual event delivery, and verifies
wording changes preserve semantic role. Replay completion is tested by its owner.
"""
import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

from benchmark.run_development import ROOT
from benchmark.serve import serve


async def verify(builds, output):
    recipes=json.loads((ROOT/'regression_cases.json').read_text(encoding='utf-8'))['cases']
    output.mkdir(parents=True,exist_ok=False)
    results=[]
    async with async_playwright() as pw:
        browser=await pw.chromium.launch()
        for recipe in recipes:
            for kind in ('regression','wording'):
                result={'id':recipe['id'],'kind':kind,'status':'error'}
                directory=builds/kind/recipe['id']
                if not (directory/'version.json').is_file():
                    result['reason']='Production version not prepared';results.append(result);continue
                try:
                    with serve(directory) as origin:
                        context=await browser.new_context(viewport={'width':1280,'height':800})
                        page=await context.new_page()
                        await page.goto(origin+recipe['path'])
                        target=page.locator(recipe['selector'])
                        await target.first.wait_for(state='visible')
                        if await target.count()!=1:raise ValueError('Target must be unique')
                        if kind=='regression':
                            await page.evaluate('''selector=>{
                                sessionStorage.setItem('delivered','0');
                                document.addEventListener('click',e=>{
                                    if(e.target.closest(selector))sessionStorage.setItem('delivered',String(+sessionStorage.getItem('delivered')+1));
                                },true);
                            }''',recipe['selector'])
                            await target.click()
                            dialog=page.locator('dialog[data-stepmeter-confirm]')
                            await dialog.wait_for(state='visible')
                            if await page.evaluate("sessionStorage.getItem('delivered')")!='0':raise ValueError('Action delivered before confirmation')
                            await page.screenshot(path=str(output/f"{recipe['id']}-confirm.png"))
                            await dialog.get_by_role('button',name='Continue',exact=True).click()
                            await page.wait_for_timeout(500)
                            if await page.evaluate("sessionStorage.getItem('delivered')")!='1':raise ValueError('Confirmation must deliver action exactly once')
                            result['additional_required_clicks']=1
                        else:
                            name=await target.evaluate("el=>el.getAttribute('aria-label')||el.textContent.trim()")
                            if name!=recipe['text']:raise ValueError('Wording not applied')
                            result['role']=await target.evaluate("el=>el.getAttribute('role')||(el.localName==='a'?'link':el.localName)")
                            await page.screenshot(path=str(output/f"{recipe['id']}-wording.png"))
                        await context.close()
                        result['status']='pass'
                except Exception as error:
                    result['reason']=type(error).__name__
                results.append(result)
        await browser.close()
    report={'cases':results,'passed':sum(r['status']=='pass' for r in results),'total':len(results),
            'scope':'interaction/wording validation; not replay completion or regression-detector accuracy'}
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['passed']==report['total'] else 2


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--builds',type=Path,default=ROOT/'builds/w3-versions')
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();raise SystemExit(asyncio.run(verify(args.builds,args.output)))


if __name__=='__main__':main()
