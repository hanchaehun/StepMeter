"""Opt-in measurement sidecar. Captures no labels; never used by rule decisions."""
from __future__ import annotations

import json
from pathlib import Path

from worker.collect.collector import resolve_element
from worker.compare.engine import screen


class EvidenceSink:
    def __init__(self, directory: Path, completion_check=None, milestones=()):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=False)
        self.rows = []
        self.completion_check = completion_check
        self.completions = {}
        self.milestones = milestones
        self.seen_milestones = {}

    async def capture(self, page, action, axe, url, attempt_id):
        seen = self.seen_milestones.setdefault(attempt_id, set())
        for i, expression in enumerate(self.milestones):
            if await page.evaluate(expression):
                seen.add(i)
        if action.action == 'done' and action.reason == 'goal_reached':
            try:
                self.completions[attempt_id] = bool(await page.evaluate(self.completion_check)) and len(seen) == len(self.milestones) if self.completion_check else None
            except Exception:
                self.completions[attempt_id] = None
        if not hasattr(action, 'target'):
            return None
        handle = await resolve_element(page, action.target)
        try:
            # Collect DOM ancestry before a click closes a menu or changes routes.
            data = await handle.evaluate('''el => {
                const doc=el.ownerDocument, nodes=[...doc.querySelectorAll('*')];
                const ids=new Map(nodes.map((n,i)=>[n,String(i)]));
                const clone=doc.documentElement.cloneNode(true);
                const copies=[clone,...clone.querySelectorAll('*')];
                nodes.forEach((n,i)=>copies[i]?.setAttribute('data-stepmeter-evidence-id',String(i)));
                // Keep sibling positions for nth-child/nth-of-type truth selectors.
                clone.querySelectorAll('script').forEach(n=>{n.type='application/x-stepmeter-inert';n.textContent='';});
                clone.querySelectorAll('style').forEach(n=>{n.textContent='';});
                clone.querySelectorAll('link').forEach(n=>n.removeAttribute('href'));
                clone.querySelectorAll('iframe').forEach(n=>{n.removeAttribute('src');n.removeAttribute('srcdoc');});
                clone.querySelectorAll('*').forEach(n=>{
                    for(const a of [...n.attributes]) if(a.name.startsWith('on') || ['src','srcset'].includes(a.name)) n.removeAttribute(a.name);
                });
                const selector = n => {
                    if(n.id) return '#'+CSS.escape(n.id);
                    const parts=[];
                    while(n && n.nodeType===1) {
                        const tag=n.localName;
                        const same=[...(n.parentElement?.children||[])].filter(x=>x.localName===tag);
                        parts.unshift(tag+':nth-of-type('+(same.indexOf(n)+1)+')');n=n.parentElement;
                    }
                    return parts.join(' > ');
                };
                return {html:clone.outerHTML, action_id:ids.get(el)||null,
                        action_selector:selector(el)};
            }''')
            # axe target selectors may refer to descendants or unrelated controls.
            mapping = {}
            for group in ('violations',):
                for rule in (axe or {}).get(group, []):
                    for node in rule['nodes']:
                        selectors = node.get('target', [])
                        if len(selectors) == 1 and isinstance(selectors[0], str):
                            mapping[json.dumps(selectors, ensure_ascii=False)] = await page.evaluate(
                                '''sel => {try {const n=document.querySelector(sel);return n ? String([...document.querySelectorAll('*')].indexOf(n)) : null;} catch {return null;}}''', selectors[0])
            return {**data, 'axe_ids': mapping, 'screen': screen(url)}
        finally:
            await handle.dispose()

    def record(self, attempt_id, step_id, idx, action, snapshot, issues, evidence):
        if evidence is None:
            return
        filename = f'{attempt_id}-{step_id}.html'
        (self.directory / filename).write_text(evidence['html'], encoding='utf-8')
        for issue in issues:
            actual_id = evidence['action_id']
            selector = evidence['action_selector']
            actual_snapshot = snapshot.model_dump()
            if issue.rule_id in ('R02', 'R10'):
                try:
                    target = json.loads(issue.explanation.rsplit(' 대상: ', 1)[1])
                    selector = target[0] if len(target) == 1 and isinstance(target[0], str) else None
                    actual_id = evidence['axe_ids'].get(json.dumps(target, ensure_ascii=False))
                    # Action snapshot describes a different target; do not invent evidence.
                    if actual_id != evidence['action_id']:
                        actual_snapshot = None
                except (ValueError, IndexError):
                    actual_id, selector, actual_snapshot = None, None, None
            self.rows.append({'issue_id': issue.id, 'attempt_id': attempt_id, 'step_id': step_id,
                'step_index': idx, 'screen': evidence['screen'], 'target_id': actual_id,
                'selector': selector, 'dom': filename, 'snapshot': actual_snapshot,
                'confusion': action.confusion, 'estimated': None})
        (self.directory / 'index.json').write_text(json.dumps(self.rows, ensure_ascii=False, indent=2), encoding='utf-8')
