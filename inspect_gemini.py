from playwright.sync_api import sync_playwright
import json
from pathlib import Path

config_path = Path("config.json").resolve()
config = json.loads(config_path.read_text(encoding="utf-8"))
user_data_dir = (config_path.parent / config["browser_user_data_dir"]).resolve()

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        str(user_data_dir),
        headless=False,
        channel=config.get("browser_channel", "chrome"),
        viewport={"width": 1440, "height": 1000},
    )
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(config["gemini_url"], wait_until="domcontentloaded")
    input("Inicia sesión si hace falta y espera a que Gemini esté listo. Pulsa ENTER para inspeccionar...")
    data = page.evaluate("""() => ({
      buttons: [...document.querySelectorAll('button, [role="button"]')].filter(e => e.offsetParent !== null)
        .map(e => ({text:(e.innerText||'').trim(), aria:e.getAttribute('aria-label'), title:e.title})).slice(0,100),
      editables: [...document.querySelectorAll('[contenteditable="true"],textarea')].filter(e => e.offsetParent !== null)
        .map(e => ({tag:e.tagName, role:e.getAttribute('role'), aria:e.getAttribute('aria-label'), placeholder:e.getAttribute('placeholder')})),
      responseTags: [...new Set([...document.querySelectorAll('model-response, message-content, .response-container')].map(e=>e.tagName+'.'+e.className))]
    })""")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    context.close()
