"""Conservative visible-control guards; these are not a general sandbox."""
import re


class SafetyStop(RuntimeError):
    pass


async def guard_target(handle, action):
    if action not in ('click', 'type', 'select'):
        return
    facts = await handle.evaluate(r'''el => ({
      type:(el.getAttribute('type')||'').toLowerCase(),
      label:[el.innerText,el.getAttribute('aria-label'),el.getAttribute('value'),el.getAttribute('title'),
        ...(el.getAttribute('aria-labelledby')||'').split(/\s+/).filter(Boolean).map(id=>el.getRootNode().getElementById?.(id)?.textContent),
        ...[...(el.labels||[])].map(label=>label.textContent)].filter(Boolean).join(' '),
      autocomplete:el.getAttribute('autocomplete')||''})''')
    if facts['type'] == 'password' or facts['autocomplete'] in ('cc-number','cc-csc','current-password','new-password'):
        raise SafetyStop('Sensitive credential/payment input')
    if action == 'click' and re.search(
            r'결제|구매\s*확정|주문\s*(완료|확정|하기)|계정\s*삭제|회원\s*탈퇴|메일\s*발송|메시지\s*(발송|전송)|'
            r'\b(pay(\s+now)?|place\s+order|confirm\s+purchase|delete\s+account|send(\s+(mail|email|message))?)\b',
            facts['label'], re.I):
        raise SafetyStop('Irreversible control')


async def blocked_reason(page):
    if await page.locator('input[type="password"]:visible').count():
        return 'login_wall'
    # Visible challenges only; do not infer a block from hidden tracking scripts.
    if await page.locator('iframe[src*="recaptcha"]:visible, iframe[src*="hcaptcha"]:visible').count():
        return 'captcha'
    text = (await page.locator('body').inner_text())[:10000].lower()
    if any(s in text for s in ('verify you are human', 'checking your browser', 'access denied',
                               '사람인지 확인', '자동입력 방지')):
        return 'bot_challenge'
    return None
