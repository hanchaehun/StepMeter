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


# Labels of irreversible controls (payment, order, account deletion, sending). click and Enter submit share it.
_IRREVERSIBLE = re.compile(
    r'결제|구매\s*확정|주문\s*(완료|확정|하기)|계정\s*삭제|회원\s*탈퇴|메일\s*발송|메시지\s*(발송|전송)|'
    r'\b(pay(\s+now)?|place\s+order|confirm\s+purchase|delete\s+account|send(\s+(mail|email|message))?)\b',
    re.I)


def is_irreversible_label(label):
    """True when a control's visible/accessible text names an irreversible action."""
    return bool(label) and _IRREVERSIBLE.search(label) is not None


# Controls an Enter submit (type submit=true) would trigger. Each candidate name joins text, value,
# aria-label, title and alt.
# 1. Input with a form owner (el.form, so a form= attribute counts): the form's default button, i.e. the
#    first in [...form.elements] that is a submit button (button type=submit or without type),
#    input[type=submit] or input[type=image]. Without one, the form's aria-label, name and title.
# 2. No form (textarea, contenteditable chat boxes): button, [role=button] and input[type=submit]
#    inside the input's ancestors up to three levels.
# 3. No candidates: nothing to check, the Enter proceeds as before.
_SUBMIT_CANDIDATES = r'''el => {
  const name = node => [node.innerText || node.textContent, node.getAttribute('value'), node.getAttribute('aria-label'),
    node.getAttribute('title'), node.getAttribute('alt')].filter(Boolean).join(' ');
  const out = [];
  if (el.form) {
    const button = [...el.form.elements].find(node =>
      (node.tagName === 'BUTTON' && node.type === 'submit') ||
      (node.tagName === 'INPUT' && ['submit', 'image'].includes(node.type)));
    out.push(button ? name(button) :
      [el.form.getAttribute('aria-label'), el.form.getAttribute('name'), el.form.getAttribute('title')].filter(Boolean).join(' '));
  } else {
    let ancestor = el.parentElement;
    for (let level = 0; level < 3 && ancestor; level++, ancestor = ancestor.parentElement) {
      for (const node of ancestor.querySelectorAll('button, [role=button], input[type=submit]')) out.push(name(node));
    }
  }
  return out.filter(Boolean);
}'''


async def guard_target(handle, action, *, task_description='', text=None, submit=False):
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
    if action == 'click' and is_irreversible_label(facts['label']):
        raise SafetyStop('Irreversible control')
    if action == 'type' and submit:
        # Enter submit: the same irreversible judgement as click, on what the Enter would trigger.
        if any(is_irreversible_label(label) for label in await handle.evaluate(_SUBMIT_CANDIDATES)):
            raise SafetyStop('Irreversible submit')


async def blocked_reason(page):
    # Visible challenges only; do not infer a block from hidden tracking scripts.
    if await page.locator('iframe[src*="recaptcha"]:visible, iframe[src*="hcaptcha"]:visible').count():
        return 'captcha'
    text = (await page.locator('body').inner_text())[:10000].lower()
    if any(s in text for s in ('verify you are human', 'checking your browser', 'access denied',
                               '사람인지 확인', '자동입력 방지')):
        return 'bot_challenge'
    return None
