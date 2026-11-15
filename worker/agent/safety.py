"""Conservative visible-control guards; these are not a general sandbox."""
import re


class SafetyStop(RuntimeError):
    pass


class LoginWall(RuntimeError):
    pass


# Token boundaries: whitespace, any non-ASCII character (e.g. Korean particles), brackets and quotes.
_TOKEN_BOUNDARY = re.compile(r'[\s"\'`()\[\]{}]|[^\x00-\x7f]')


def _literal_in_task(task_description, value):
    """True only when value equals one task token exactly (case-sensitive).

    Trailing . , ; : on a token may be dropped; other symbols (! ? @ # ...) stay part of the token.
    """
    if not value or not value.strip():
        return False
    for token in _TOKEN_BOUNDARY.split(task_description or ''):
        if token and value in (token, token.rstrip('.,;:')):
            return True
    return False


async def guard_target(handle, action, *, task_description='', text=None):
    if action not in ('click', 'type', 'select'):
        return
    facts = await handle.evaluate(r'''el => ({
      type:(el.getAttribute('type')||'').toLowerCase(),
      label:[el.innerText,el.getAttribute('aria-label'),el.getAttribute('value'),el.getAttribute('title'),
        ...(el.getAttribute('aria-labelledby')||'').split(/\s+/).filter(Boolean).map(id=>el.getRootNode().getElementById?.(id)?.textContent),
        ...[...(el.labels||[])].map(label=>label.textContent)].filter(Boolean).join(' '),
      autocomplete:el.getAttribute('autocomplete')||''})''')
    autocomplete = set(facts['autocomplete'].lower().split())
    if autocomplete.intersection(('cc-number', 'cc-csc')):
        raise SafetyStop('Sensitive credential/payment input')
    if (facts['type'] == 'password' or autocomplete.intersection(('current-password', 'new-password'))) and action == 'type':
        if not _literal_in_task(task_description, text):
            raise LoginWall('Password value is absent from task')
    if action == 'click' and re.search(
            r'결제|구매\s*확정|주문\s*(완료|확정|하기)|계정\s*삭제|회원\s*탈퇴|메일\s*발송|메시지\s*(발송|전송)|'
            r'\b(pay(\s+now)?|place\s+order|confirm\s+purchase|delete\s+account|send(\s+(mail|email|message))?)\b',
            facts['label'], re.I):
        raise SafetyStop('Irreversible control')


async def blocked_reason(page):
    # Visible challenges only; do not infer a block from hidden tracking scripts.
    if await page.locator('iframe[src*="recaptcha"]:visible, iframe[src*="hcaptcha"]:visible').count():
        return 'captcha'
    text = (await page.locator('body').inner_text())[:10000].lower()
    if any(s in text for s in ('verify you are human', 'checking your browser', 'access denied',
                               '사람인지 확인', '자동입력 방지')):
        return 'bot_challenge'
    return None
