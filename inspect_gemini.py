from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, channel="chrome")
    page = browser.new_page()
    page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    input("Inicia sesión si hace falta y deja abierto un chat nuevo. Pulsa ENTER aquí para inspeccionar...")
    data = page.evaluate("""() => ({
      buttons: [...document.querySelectorAll('button')].filter(e => e.offsetParent !== null)
        .map(e => ({text:(e.innerText||'').trim(), aria:e.getAttribute('aria-label'), title:e.title})).slice(0,100),
      editables: [...document.querySelectorAll('[contenteditable="true"],textarea')].filter(e => e.offsetParent !== null)
        .map(e => ({tag:e.tagName, role:e.getAttribute('role'), aria:e.getAttribute('aria-label'), placeholder:e.getAttribute('placeholder')})),
      responseTags: [...new Set([...document.querySelectorAll('model-response, message-content, .response-container')].map(e=>e.tagName+'.'+e.className))]
    })""")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    browser.close()
