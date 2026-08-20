"""
Actions custom browser-use utilisees par l'agent d'exploration.

Contient toutes les @controller.action : navigation robuste, capture de
outerHTML avant interaction (clic/saisie), gestion des bannieres cookies
(y compris Shadow DOM), et detection du premier lien produit.

Ce fichier definit l'objet `controller` (instance de Controller) qui doit
etre importe et passe a l'Agent dans search_product.py.
"""

from browser_use import Controller, ActionResult
from browser_use.browser.context import BrowserContext

controller = Controller()

_CAPTURE_JS = """
el => {
    const openTagMatch = el.outerHTML.match(/^<[^>]+>/);
    const openTag = openTagMatch ? openTagMatch[0] : el.outerHTML.slice(0, 300);
    const text = (el.innerText || el.textContent || '').trim().slice(0, 80);
    const tag = el.tagName ? el.tagName.toLowerCase() : 'div';
    return text ? `${openTag}${text}</${tag}>` : openTag;
}
"""


def _sanitize_html(html: str) -> str:
    return html.replace('"', "'") if html else html


@controller.action(
    "Navigue vers une URL de maniere robuste (timeout long, attend "
    "domcontentloaded plutot que load). Utilise TOUJOURS cette action a la "
    "place de l'action standard go_to_url."
)
async def robust_goto(url: str, browser: BrowserContext) -> ActionResult:
    page = await browser.get_current_page()
    last_error = None
    for _ in range(2):
        try:
            await page.goto(url, timeout=60000, wait_until="domcontentloaded")
            await page.wait_for_timeout(1000)
            return ActionResult(extracted_content=f"Navigation reussie vers {url}.", include_in_memory=True)
        except Exception as e:
            last_error = e
    return ActionResult(extracted_content=f"Echec navigation vers {url}: {last_error}", include_in_memory=True)


@controller.action(
    "Capture le outerHTML exact d'un element via son index PUIS clique "
    "dessus, en une seule action atomique. A utiliser pour le bouton "
    "cookies et le lien produit."
)
async def capture_and_click(index: int, browser: BrowserContext) -> ActionResult:
    try:
        el = await browser.get_element_by_index(index)
        if el is None:
            return ActionResult(extracted_content=f"Element index {index} introuvable.", include_in_memory=True)
        html = _sanitize_html(await el.evaluate(_CAPTURE_JS))
        await el.click()
        return ActionResult(extracted_content=f"HTML capture avant clic: {html}", include_in_memory=True)
    except Exception as e:
        return ActionResult(
            extracted_content=f"Erreur capture_and_click index {index}: {e}. "
                               "Si 'intercepts pointer events', utilise dismiss_cookie_banner.",
            include_in_memory=True,
        )


@controller.action(
    "Capture le outerHTML exact d'un element via son index PUIS tape du "
    "texte dedans, en une seule action atomique. A utiliser pour l'input "
    "de recherche."
)
async def capture_and_type(index: int, text: str, browser: BrowserContext) -> ActionResult:
    try:
        el = await browser.get_element_by_index(index)
        if el is None:
            return ActionResult(extracted_content=f"Element index {index} introuvable.", include_in_memory=True)
        html = _sanitize_html(await el.evaluate(_CAPTURE_JS))
        await el.fill(text)
        return ActionResult(extracted_content=f"HTML capture avant saisie: {html}", include_in_memory=True)
    except Exception as e:
        return ActionResult(
            extracted_content=f"Erreur capture_and_type index {index}: {e}. "
                               "Si 'intercepts pointer events', utilise dismiss_cookie_banner.",
            include_in_memory=True,
        )


@controller.action(
    "Capture le outerHTML exact d'un element via son index, SANS "
    "interagir. A utiliser pour lire PRIX ou STOCK."
)
async def capture_real_html(index: int, browser: BrowserContext) -> ActionResult:
    try:
        el = await browser.get_element_by_index(index)
        if el is None:
            return ActionResult(extracted_content=f"Element index {index} introuvable.", include_in_memory=True)
        html = _sanitize_html(await el.evaluate(_CAPTURE_JS))
        return ActionResult(extracted_content=html, include_in_memory=True)
    except Exception as e:
        return ActionResult(extracted_content=f"Erreur capture_real_html index {index}: {e}", include_in_memory=True)


_COOKIE_DISMISS_JS = """
() => {
    const strictTexts = ['accepter tout', 'tout accepter', 'accept all',
                          'akkoord alle', 'godkann alla', 'godkänn alla',
                          'zaakceptuj wszystko', 'aceptar todo',
                          'godta alle', 'hyväksy kaikki'];
    const looseTexts = ['accepter', 'accept', 'ok', 'akkoord', 'godkann',
                         'aceptar', 'godta', 'hyväksy', 'jag godkänner'];
    function deepFind(root, texts) {
        const els = root.querySelectorAll('button, [role="button"], a');
        for (const el of els) {
            const t = (el.innerText || el.textContent || '').trim().toLowerCase();
            if (texts.some(x => t === x || t.startsWith(x))) return el;
        }
        for (const el of root.querySelectorAll('*')) {
            if (el.shadowRoot) {
                const found = deepFind(el.shadowRoot, texts);
                if (found) return found;
            }
        }
        return null;
    }
    let btn = deepFind(document, strictTexts);
    if (!btn) btn = deepFind(document, looseTexts);
    if (!btn) return { clicked: false };
    btn.click();
    return { clicked: true, label: (btn.innerText || '').trim() };
}
"""


@controller.action(
    "Cherche et clique un bouton d'acceptation cookies meme dans un "
    "Shadow DOM (Usercentrics, OneTrust, Didomi...). A utiliser des qu'un "
    "clic echoue avec 'intercepts pointer events'."
)
async def dismiss_cookie_banner(browser: BrowserContext) -> ActionResult:
    try:
        page = await browser.get_current_page()
        result = None
        for _ in range(3):
            result = await page.evaluate(_COOKIE_DISMISS_JS)
            if not result.get("clicked"):
                break
            await page.wait_for_timeout(600)
        msg = "Banniere cookies fermee." if result and result.get("clicked") else "Aucune banniere trouvee."
        return ActionResult(extracted_content=msg, include_in_memory=True)
    except Exception as e:
        return ActionResult(extracted_content=f"Erreur dismiss_cookie_banner: {e}", include_in_memory=True)


@controller.action(
    "Trouve et clique le lien du PREMIER produit d'une page de resultats "
    "via recherche JS directe dans le DOM, puis retourne son outerHTML. A "
    "utiliser EN PRIORITE avant de chercher un index a la main."
)
async def capture_and_click_first_product(browser: BrowserContext) -> ActionResult:
    try:
        page = await browser.get_current_page()
        result = await page.evaluate(
            """
            () => {
                const productPatterns = ['/p/', '/product', '/produkt', '/produit',
                                          '/artikel', '/item/', '.html'];
                const badAncestors = 'nav, header, footer, [class*="menu"]';
                const links = Array.from(document.querySelectorAll('a[href]'));
                for (const a of links) {
                    const href = a.getAttribute('href') || '';
                    const text = (a.innerText || '').trim();
                    if (text.length < 3) continue;
                    if (a.closest(badAncestors)) continue;
                    if (!productPatterns.some(p => href.includes(p))) continue;
                    const rect = a.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) continue;
                    const openTagMatch = a.outerHTML.match(/^<[^>]+>/);
                    const openTag = openTagMatch ? openTagMatch[0] : a.outerHTML.slice(0, 300);
                    return { found: true, href, text, html: `${openTag}${text}</a>` };
                }
                return { found: false };
            }
            """
        )
        if not result.get("found"):
            return ActionResult(
                extracted_content="Aucun lien produit trouve via JS. Cherche un index manuellement.",
                include_in_memory=True,
            )
        html = _sanitize_html(result.get("html", ""))
        href = result.get("href")
        if href:
            await page.evaluate(
                "(href) => { const a = document.querySelector(`a[href='${href}']`); if (a) a.click(); }",
                href,
            )
        return ActionResult(extracted_content=f"HTML capture avant clic: {html}", include_in_memory=True)
    except Exception as e:
        return ActionResult(extracted_content=f"Erreur capture_and_click_first_product: {e}", include_in_memory=True)


@controller.action(
    "Capture le outerHTML du plus petit element contenant un texte donne, "
    "sans index cliquable. A utiliser pour le STOCK quand c'est du texte "
    "brut (ex: 'En stock')."
)
async def capture_by_text(text: str, browser: BrowserContext) -> ActionResult:
    try:
        page = await browser.get_current_page()
        html = await page.evaluate(
            """
            (searchText) => {
                const norm = s => (s || '').trim().toLowerCase();
                const target = norm(searchText);
                if (!target) return null;
                const badAncestors = 'nav, header, footer, [class*="menu"], [class*="cart"], [class*="basket"], [class*="winkelwagen"]';
                const all = document.querySelectorAll('body *');
                let best = null, bestLen = Infinity;
                for (const el of all) {
                    if (el.closest(badAncestors)) continue;
                    const full = norm(el.innerText || el.textContent || '');
                    if (full.includes(target) && full.length < bestLen) {
                        bestLen = full.length;
                        best = el;
                    }
                }
                if (!best) return null;
                const openTagMatch = best.outerHTML.match(/^<[^>]+>/);
                const openTag = openTagMatch ? openTagMatch[0] : best.outerHTML.slice(0, 300);
                const bestText = (best.innerText || best.textContent || '').trim().slice(0, 80);
                const bestTag = best.tagName ? best.tagName.toLowerCase() : 'div';
                return `${openTag}${bestText}</${bestTag}>`;
            }
            """,
            text,
        )
        if not html:
            return ActionResult(extracted_content=f"Aucun element trouve contenant '{text}'.", include_in_memory=True)
        return ActionResult(extracted_content=_sanitize_html(html), include_in_memory=True)
    except Exception as e:
        return ActionResult(extracted_content=f"Erreur capture_by_text: {e}", include_in_memory=True)