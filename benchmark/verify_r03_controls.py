"""Local synthetic reproduction of #77 controls; reports evidence, no remote site."""
import asyncio
import json
from playwright.async_api import async_playwright
from worker.driver.effects import EffectObserver

HTML = """<html lang="en"><title>R03 reproduction</title><style>
.cart-preview {display:none}.cart-preview.active {display:block}
</style><input type="search" oninput="document.querySelector('#products').textContent=this.value">
<form onsubmit="event.preventDefault()"><button>Search</button></form>
<a href="#" id="cart" onclick="event.preventDefault();document.querySelector('.cart-preview').classList.toggle('active')">Cart</a>
<div class="cart-preview">Cart contents</div><p id="products">Vegetables</p></html>"""


async def verify():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page()
            await page.route('**/*',lambda route:route.abort())
            await page.set_content(HTML)
            observer = EffectObserver(page)
            try:
                search = await observer.click(page.locator('button'))
                before = await page.locator('.cart-preview').is_visible()
                cart = await observer.click(page.locator('#cart'))
                after = await page.locator('.cart-preview').is_visible()
                if search.effect_type != 'no_change' or before or not after:
                    raise AssertionError('Synthetic source behavior changed')
                return dict(search=dict(effect=search.effect_type, expected='genuine_no_change'),
                            cart=dict(effect=cart.effect_type, before_visible=before,
                                      after_visible=after, visibility_missed=cart.effect_type=='no_change'))
            finally:
                await observer.aclose()
        finally:
            await browser.close()


if __name__ == '__main__':
    print(json.dumps(asyncio.run(verify()),indent=2))
