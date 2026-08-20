"""
Scraper autonome généré automatiquement pour : https://www.medpets.nl
Aucun LLM requis. Basé sur Playwright uniquement.
Utilisation : python scraper_www_medpets_nl.py "nom du produit à chercher"
"""

import sys
from playwright.sync_api import sync_playwright

SITE_URL = "https://www.medpets.nl"
DOMAIN = "www.medpets.nl"
URL_PATTERN = '__SLUG__'

SELECTORS = {
    "cookie_button": 'button[type="button"]',
    "search_input": '#search',
    "search_button": 'button[aria-label="Zoeken"]',
    "price": 'div.my-4.radio',
    "stock": 'div.flex',
}


STOCK_KEYWORDS = [
    "op voorraad", "niet op voorraad", "in stock", "out of stock",
    "en stock", "rupture de stock", "auf lager", "nicht auf lager",
    "en existencia", "agotado",
]


def find_price_generic(page):
    """Repli générique : cherche le premier élément dont le texte
    ressemble à un prix (symbole monétaire + chiffres), sans dépendre
    d'une valeur figée capturée pendant l'exploration (le prix change
    selon le produit)."""
    js = r"""
    () => {
        const re = /(€|\$|£)\s?\d+[.,]\d{2}|\d+[.,]\d{2}\s?(€|\$|£)/;
        const els = document.querySelectorAll('body *');
        for (const el of els) {
            if (el.children.length > 0) continue;  // élément feuille seulement
            const text = (el.innerText || el.textContent || '').trim();
            if (text.length < 100 && re.test(text)) return text;
        }
        return null;
    }
    """
    return page.evaluate(js)


def find_stock_generic(page):
    """Repli générique : cherche le premier élément dont le texte
    correspond à un mot-clé de stock connu (multilingue), sans dépendre
    du texte exact capturé pendant l'exploration."""
    js = r"""
    (keywords) => {
        const els = document.querySelectorAll('body *');
        for (const el of els) {
            if (el.children.length > 0) continue;
            const text = (el.innerText || el.textContent || '').trim().toLowerCase();
            if (text.length < 60 && keywords.some(k => text.includes(k))) {
                return (el.innerText || el.textContent || '').trim();
            }
        }
        return null;
    }
    """
    return page.evaluate(js, STOCK_KEYWORDS)


def find_first_product_link(page):
    """Trouve le lien du premier produit via un fallback JS générique
    basé sur le pattern d'URL détecté pendant l'exploration."""
    js = """
    (pattern) => {
        const badAncestors = 'nav, header, footer, [class*="menu"], [class*="carousel"], [class*="banner"], [class*="slider"]';
        const links = Array.from(document.querySelectorAll('a[href]'));
        for (const a of links) {
            const href = a.getAttribute('href') || '';
            const text = (a.innerText || '').trim();
            if (text.length < 3) continue;
            if (a.closest(badAncestors)) continue;
            const rect = a.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) continue;
            if (pattern === '__SLUG__') {
                const slug = href.split('/').filter(Boolean).pop() || '';
                if (slug.includes('-')) return href;
            } else if (href.includes(pattern)) {
                return href;
            }
        }
        return null;
    }
    """
    return page.evaluate(js, URL_PATTERN)


def scrape(product_name: str) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=350,  # ralentit chaque action pour bien voir ce qui se passe
            args=["--no-sandbox", "--disable-gpu"],
        )
        page = browser.new_page()

        print(f"→ Ouverture de {SITE_URL} ...")
        page.goto(SITE_URL, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        # Cookies
        if SELECTORS["cookie_button"]:
            try:
                print("→ Fermeture de la bannière cookies ...")
                page.locator(SELECTORS["cookie_button"]).first.click(timeout=3000)
                page.wait_for_timeout(500)
            except Exception:
                print("  (pas de bannière cookies visible, on continue)")

        # Recherche
        if not SELECTORS["search_input"]:
            browser.close()
            raise RuntimeError("Sélecteur de recherche introuvable pour ce site.")
        print(f"→ Recherche de '{product_name}' ...")
        page.locator(SELECTORS["search_input"]).first.fill(product_name)
        page.wait_for_timeout(300)
        if SELECTORS["search_button"]:
            try:
                page.locator(SELECTORS["search_button"]).first.click(timeout=3000)
            except Exception:
                page.keyboard.press("Enter")
        else:
            page.keyboard.press("Enter")
        page.wait_for_timeout(2500)
        print(f"  Page de résultats : {page.url}")

        # Premier produit
        href = find_first_product_link(page)
        if not href:
            browser.close()
            raise RuntimeError("Aucun lien produit trouvé pour cette recherche.")
        if href.startswith("/"):
            href = f"https://{DOMAIN}{href}"
        print(f"→ Ouverture de la fiche produit : {href}")
        page.goto(href, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        data = {"url": href, "name": None, "price": None, "stock": None}

        try:
            data["name"] = page.title()
        except Exception:
            pass

        import re as _re
        PRICE_RE = _re.compile(r"(€|\$|£)\s?\d+[.,]\d{2}|\d+[.,]\d{2}\s?(€|\$|£)")

        if SELECTORS["price"]:
            try:
                candidate = page.locator(SELECTORS["price"]).first.inner_text(timeout=3000).strip()
                # On ne garde le sélecteur que si son texte ressemble vraiment
                # à un prix (court + motif monétaire) : un sélecteur trop
                # générique (ex: "div.flex") peut matcher un tout autre
                # élément (menu, header) selon la page/le produit.
                if candidate and len(candidate) < 40 and PRICE_RE.search(candidate):
                    data["price"] = candidate
            except Exception:
                pass
        if not data["price"]:
            try:
                data["price"] = find_price_generic(page)
            except Exception:
                pass

        if SELECTORS["stock"]:
            try:
                candidate = page.locator(SELECTORS["stock"]).first.inner_text(timeout=3000).strip()
                if candidate and len(candidate) < 60 and any(k in candidate.lower() for k in STOCK_KEYWORDS):
                    data["stock"] = candidate
            except Exception:
                pass
        if not data["stock"]:
            try:
                data["stock"] = find_stock_generic(page)
            except Exception:
                pass

        print("→ Données récupérées, fermeture dans 2 secondes ...")
        page.wait_for_timeout(2000)
        browser.close()
        return data


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scraper_www_medpets_nl.py \"nom du produit\"")
        sys.exit(1)
    result = scrape(sys.argv[1])
    print("\n=== Résultat ===")
    for k, v in result.items():
        print(f"{k}: {v}")
