"""Apply a single reproducible mutation to a development page (no source writes)."""
from __future__ import annotations

import json
from pathlib import Path

from playwright.async_api import Page


def load_config(path: Path) -> dict:
    # JSON is a YAML 1.2 subset; avoid another runtime dependency.
    config = json.loads(path.read_text(encoding="utf-8"))
    if config["operation"] not in {"style", "no_handler", "overlay", "remove_name", "tiny_toolbar"}:
        raise ValueError("unsupported mutation operation")
    return config


async def apply(page: Page, config: dict) -> None:
    target = page.locator(config["selector"])
    if await target.count() != 1:
        raise ValueError("mutation selector must match exactly one element")
    await target.evaluate("""(el, c) => {
      switch(c.operation) {
        case 'tiny_toolbar': {
          Object.assign(el.style,c.style);
          const help=document.createElement('button'); help.type='button';
          help.textContent='?'; help.setAttribute('aria-label','가입 도움말');
          Object.assign(help.style,c.style); help.onclick=()=>{help.textContent='!'};
          el.after(help); break;
        }
        case 'style': Object.assign(el.style,c.style); break;
        case 'no_handler': el.closest('form').onsubmit = e => e.preventDefault(); break;
        case 'remove_name': el.textContent=''; el.removeAttribute('aria-label'); break;
        case 'overlay': {
          const r=el.getBoundingClientRect(), overlay=document.createElement('div');
          overlay.id='leftover-overlay'; overlay.setAttribute('aria-hidden','true');
          Object.assign(overlay.style,{position:'absolute',left:`${r.x+scrollX}px`,
            top:`${r.y+scrollY}px`,width:`${r.width}px`,height:`${r.height}px`,
            background:'rgba(255,255,255,.5)',zIndex:'5'});
          document.querySelector('main').append(overlay); break;
        }
      }
    }""", config)
