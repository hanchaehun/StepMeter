"""Deterministic observation projection; never renumber collector targets."""
import base64
import hashlib
import json
from urllib.parse import urlsplit


def state_hash(url, elements):
    names = sorted(str(row.get('name') or row.get('label_text') or '') for row in elements)
    payload = [urlsplit(url).path or '/', names]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


LIMIT = 60  # LLM에 보내는 요소 수 (ADR 0011 11번, 이전 30은 ADR 0010)
SORT_ONLY = 'sort'  # collect.js observe()의 정렬 전용 필드 (#75). LLM 항목에는 넣지 않는다


async def describe(elements, driver):
    """LLM에 보낼 요소 목록. 60개 이하면 문서 순서 그대로, 넘으면 아래 순서로 60개를 고른다 (#75).

    1. 열린 겹침 층(dialog·listbox·menu 등) 안의 요소  2. 가려지지 않은 요소  3. 텍스트 입력칸
    4. main 안 → 화면 중심에 가까운 순 → 큰 순 → el_id. 가려진 요소는 60개 안이면 "(가려짐)"으로 남긴다 (ADR 0010).
    번호 라벨 스크린샷은 이 행들에 그린다. 모델에는 prompt_line()으로 바꾼 한 줄씩 보낸다 (action_v4).
    """
    viewport = driver.page.viewport_size or {'width': 1280, 'height': 800}
    def priority(row):
        b = row['bbox']
        hint = row.get(SORT_ONLY) or {}
        distance = (b['x']+b['width']/2-viewport['width']/2)**2 + (b['y']+b['height']/2-viewport['height']/2)**2
        return (not hint.get('overlay'), bool(row.get('occluded')), not hint.get('text_input'),
                row.get('landmark') != 'main', distance, -b['width']*b['height'], row['el_id'])
    rows = []
    for row in (sorted(elements, key=priority) if len(elements) > LIMIT else elements)[:LIMIT]:
        item = {k: v for k, v in row.items() if k != SORT_ONLY}
        if row.get('occluded'):
            item['visibility'] = '(가려짐)'
        if row.get('tag') == 'select':
            options = await driver.select_options(row['el_id'])
            item['options'] = [dict(option=i, text=o['label'])
                               for i, o in enumerate(options or [], 1)]
        rows.append(item)
    return rows


def prompt_line(row):
    """모델에 보내는 한 줄 (prompts/action_v4.md "요소 목록").

    번호|역할(없으면 태그)|이름(없으면 label_text)|영역(없으면 -)|x,y,너비x높이(정수)|표시
    표시는 가려짐, 입력됨, 비어 있음, 선택됨, 펼쳐짐, 비활성을 쉼표로 잇는다. select는 줄 끝에 옵션 목록을 붙인다.
    입력값은 state에 없으므로 줄에도 들어가지 않는다.
    """
    b = row['bbox']
    state = row.get('state') or {}
    marks = []
    if row.get('occluded'):
        marks.append('가려짐')
    if 'filled' in state:
        marks.append('입력됨' if state['filled'] else '비어 있음')
    if state.get('checked') or state.get('selected'):
        marks.append('선택됨')
    if state.get('expanded'):
        marks.append('펼쳐짐')
    if state.get('disabled'):
        marks.append('비활성')
    line = '|'.join((str(row['el_id']), row.get('role') or row['tag'],
                     _field(row.get('name') or row.get('label_text')), row.get('landmark') or '-',
                     f"{round(b['x'])},{round(b['y'])},{round(b['width'])}x{round(b['height'])}",
                     ','.join(marks)))
    if 'options' in row:
        line += '|옵션: ' + ', '.join(f"{o['option']}={_field(o['text'])}" for o in row['options'])
    return line


def _field(text):
    """Page text inside a line: "|" would shift the columns, so it becomes "/" (as worker/rules/r09.py)."""
    return (text or '').replace('|', '/')


def target_name(element):
    """최근 행동 기록용 "역할:이름" (역할이 없으면 태그, 이름이 없으면 label_text)."""
    return f"{element.role or element.tag}:{element.name or element.label_text or ''}"


async def labeled_screenshot(page, rows):
    """Draw labels on a detached canvas, without changing the measured DOM."""
    raw = await page.screenshot(type='jpeg', quality=70, caret='initial')
    result = await page.evaluate('''async ({image, rows}) => {
      const img = new Image(); img.src = 'data:image/jpeg;base64,' + image;
      await img.decode();
      const c = document.createElement('canvas'); c.width=img.width; c.height=img.height;
      const ctx=c.getContext('2d'); ctx.drawImage(img,0,0);
      const scale=img.width/innerWidth;
      ctx.scale(scale,scale); ctx.font='bold 13px sans-serif';
      for (const r of rows) {
        const x=Math.max(0,Math.min(innerWidth-30,r.bbox.x));
        const y=Math.max(14,Math.min(innerHeight,r.bbox.y+14));
        ctx.fillStyle='#c00'; ctx.fillRect(x,y-14,30,17);
        ctx.fillStyle='white'; ctx.fillText(String(r.el_id),x+2,y);
      }
      return c.toDataURL('image/jpeg',0.7).split(',')[1];
    }''', {'image': base64.b64encode(raw).decode(), 'rows': rows})
    return base64.b64decode(result)
