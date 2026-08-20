"""
Scraper autonome généré automatiquement pour : https://www.petsplace.nl
Aucun LLM requis. Basé sur Playwright uniquement.
Utilisation : python scraper_www_petsplace_nl.py "nom du produit à chercher"
"""

import sys
from playwright.sync_api import sync_playwright

SITE_URL = "https://www.petsplace.nl"
DOMAIN = "www.petsplace.nl"
URL_PATTERN = '__SLUG__'

SELECTORS = {
    "cookie_button": 'button:has-text("Tout autoriser")',
    "search_input": '#autocomplete-0-input',
    "search_button": '',
    "price": 'span.normal-price.special-price',
    "stock": 'div.stock.available',
}


STOCK_KEYWORDS = [
    "op voorraad", "niet op voorraad", "in stock", "out of stock",
    "en stock", "rupture de stock", "auf lager", "nicht auf lager",
    "en existencia", "agotado", "disponible", "no disponible",
    "i lager", "ej i lager", "slut i lager", "finns i lager",
    "på lager", "ikke på lager", "varastossa", "ei varastossa",
    "disponibile", "non disponibile", "esaurito",
]


_COOKIE_DISMISS_JS = r"""
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
    return { clicked: true };
}
"""


def dismiss_cookies(page):
    closed = False
    if SELECTORS["cookie_button"]:
        try:
            page.locator(SELECTORS["cookie_button"]).first.click(timeout=3000)
            closed = True
        except Exception:
            pass
    try:
        for _ in range(3):
            result = page.evaluate(_COOKIE_DISMISS_JS)
            if not result.get("clicked"):
                break
            closed = True
            page.wait_for_timeout(500)
    except Exception:
        pass
    return closed


def find_price_generic(page):
    js = r"""
    () => {
        const re = /(€|\$|£)\s?\d+[.,]\d{2}|\d+[.,]\d{2}\s?(€|\$|£)|\d+[.,]\d{2}\s?kr/i;
        const badAncestors = 'nav, header, footer, [class*="menu"], [class*="cart"], [class*="basket"], [class*="winkelwagen"]';
        function isVisible(el) {
            const rect = el.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) === 0) return false;
            return true;
        }
        const els = document.querySelectorAll('body *');
        for (const el of els) {
            if (el.children.length > 0) continue;
            if (el.closest(badAncestors)) continue;
            if (!isVisible(el)) continue;
            const text = (el.innerText || el.textContent || '').trim();
            if (text.length < 100 && re.test(text)) return text;
        }
        return null;
    }
    """
    return page.evaluate(js)


def find_stock_generic(page):
    js = r"""
    (keywords) => {
        const badAncestors = 'nav, header, footer, [class*="menu"], [class*="cart"], [class*="basket"], [class*="winkelwagen"]';
        function isVisible(el) {
            const rect = el.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) === 0) return false;
            return true;
        }
        const els = document.querySelectorAll('body *');
        for (const el of els) {
            if (el.children.length > 0) continue;
            if (el.closest(badAncestors)) continue;
            if (!isVisible(el)) continue;
            const text = (el.innerText || el.textContent || '').trim().toLowerCase();
            if (text.length < 60 && keywords.some(k => text.includes(k))) {
                return (el.innerText || el.textContent || '').trim();
            }
        }
        return null;
    }
    """
    return page.evaluate(js, STOCK_KEYWORDS)


def list_product_links(page, product_name=""):
    """Liste TOUS les liens produits candidats sur la page, TRIÉS par
    pertinence par rapport au produit recherché (les candidats dont le
    texte visible ou l'URL contiennent au moins un mot de la recherche
    passent en premier).

    Indispensable : sans ce tri, le premier lien "produit" trouvé dans
    l'ordre du DOM peut être un widget "produits populaires"/publicité
    présent sur TOUTES les pages du site (pas seulement les résultats de
    recherche), menant à un produit totalement sans rapport avec la
    recherche -- observé sur happypet.cz où toute recherche atterrissait
    sur le même produit "Alavis Triple Blend", peu importe le terme tapé.
    """
    js = """
    (params) => {
        const { pattern, searchWords } = params;
        const badAncestors = 'nav, header, footer, [class*="menu"]';
        const excludeKeywords = ['promozioni', 'promotion', 'promo', 'negozio', 'negozi',
            'store-locator', 'store', 'categoria', 'categorie', 'category', 'collezione',
            'collection', 'marchi', 'marques', 'brands', 'brand', 'blog', 'chi-siamo',
            'about-us', 'contatti', 'contact', 'assistenza', 'help', 'faq', 'account',
            'login', 'carrello', 'cart', 'checkout', 'privacy', 'cookie', 'termini',
            'terms', 'newsletter'];
        const links = Array.from(document.querySelectorAll('a[href]'));
        const seen = new Set();
        const relevant = [];
        const others = [];
        for (const a of links) {
            const href = a.getAttribute('href') || '';
            const text = (a.innerText || '').trim();
            if (text.length < 3) continue;
            if (a.closest(badAncestors)) continue;
            const rect = a.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) continue;
            const hrefPath = href.split('?')[0].split('#')[0];
            const segments = hrefPath.split('/').filter(Boolean);
            let matches = false;
            if (pattern === '__SLUG__') {
                const slug = segments[segments.length - 1] || '';
                matches = slug.includes('-');
            } else if (pattern === '__TRAILING_P__') {
                matches = segments.length > 0 && segments[segments.length - 1] === 'p';
            } else {
                matches = href.includes(pattern);
            }
            if (matches && (pattern === '__SLUG__' || pattern === '__TRAILING_P__')) {
                const lowerPath = hrefPath.toLowerCase();
                if (excludeKeywords.some(k => lowerPath.includes(k))) matches = false;
            }
            if (matches && !seen.has(href)) {
                seen.add(href);
                const haystack = (text + ' ' + hrefPath).toLowerCase();
                const isRelevant = searchWords.length === 0 ||
                    searchWords.some(w => w.length >= 3 && haystack.includes(w));
                if (isRelevant) {
                    relevant.push(href);
                } else {
                    others.push(href);
                }
            }
        }
        // Les candidats pertinents (texte/URL matchant un mot de la
        // recherche) passent en premier ; les autres restent en secours
        // seulement si aucun candidat pertinent n'a ete trouve.
        return relevant.length > 0 ? relevant : others;
    }
    """
    search_words = [w.lower() for w in product_name.split() if len(w) >= 3]
    return page.evaluate(js, {"pattern": URL_PATTERN, "searchWords": search_words})


def click_link_by_href(page, href):
    js = """
    (href) => {
        const a = document.querySelector(`a[href='${href}']`);
        if (a) { a.scrollIntoView({block: 'center'}); a.click(); return true; }
        return false;
    }
    """
    return page.evaluate(js, href)


NOT_FOUND_PATTERNS = [
    "page not found", "404", "hittades inte", "sidan finns inte",
    "page introuvable", "seite nicht gefunden", "pagina niet gevonden",
    "página no encontrada", "pagina non trovata",
]


def is_not_found_page(page) -> bool:
    try:
        title = (page.title() or "").lower()
        if any(p in title for p in NOT_FOUND_PATTERNS):
            return True
        body_sample = page.evaluate(
            "() => (document.body.innerText || '').slice(0, 300).toLowerCase()"
        )
        return any(p in body_sample for p in NOT_FOUND_PATTERNS)
    except Exception:
        return False


def scrape(product_name: str) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=350,
            args=["--no-sandbox", "--disable-gpu"],
        )
        page = browser.new_page()

        print(f"→ Ouverture de {SITE_URL} ...")
        page.goto(SITE_URL, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        print("→ Fermeture de la bannière cookies ...")
        if dismiss_cookies(page):
            page.wait_for_timeout(500)
        else:
            print("  (pas de bannière cookies visible, on continue)")

        if not SELECTORS["search_input"]:
            browser.close()
            raise RuntimeError("Sélecteur de recherche introuvable pour ce site.")
        print(f"→ Recherche de '{product_name}' ...")
        search_box = page.locator(SELECTORS["search_input"]).first
        search_box.fill(product_name)
        page.wait_for_timeout(300)

        submitted_via_button = False
        if SELECTORS["search_button"]:
            try:
                page.locator(SELECTORS["search_button"]).first.click(timeout=3000)
                submitted_via_button = True
            except Exception:
                pass
        if not submitted_via_button:
            try:
                search_box.press("Enter")
            except Exception:
                pass
        page.wait_for_timeout(2500)

        if page.url.rstrip("/") == SITE_URL.rstrip("/"):
            print("  (recherche non soumise, nouvelle tentative avec Entrée) ...")
            try:
                search_box.press("Enter")
            except Exception:
                pass
            page.wait_for_timeout(3000)
        print(f"  Page de résultats : {page.url}")

        candidates = list_product_links(page, product_name)
        if not candidates:
            # Certains sites chargent les résultats en différé (AJAX) et
            # ont besoin de plus de temps que le délai standard -- avant
            # d'abandonner, on attend un peu plus et on retente une fois.
            print("  (aucun produit détecté, nouvelle tentative après un délai plus long) ...")
            page.wait_for_timeout(3000)
            candidates = list_product_links(page, product_name)
        if not candidates:
            browser.close()
            raise RuntimeError("Aucun lien produit trouvé pour cette recherche.")

        results_url = page.url
        opened = False
        for i, href in enumerate(candidates[:5]):
            if i == 0:
                print(f"→ Clic sur le produit {i + 1}/{len(candidates)} ...")
                click_link_by_href(page, href)
            else:
                print(f"  Lien précédent invalide/périmé, essai du produit {i + 1} ...")
                page.goto(results_url, timeout=60000, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
                click_link_by_href(page, href)
            page.wait_for_timeout(2000)

            if page.url == results_url:
                full_href = href if href.startswith("http") else f"https://{DOMAIN}{href}"
                page.goto(full_href, timeout=60000, wait_until="domcontentloaded")
                page.wait_for_timeout(1000)

            if not is_not_found_page(page):
                print(f"→ Fiche produit ouverte : {page.url}")
                opened = True
                break
            print(f"  ⚠️  Page 404 détectée sur ce lien.")

        if not opened:
            browser.close()
            raise RuntimeError(
                "Tous les liens produits candidats mènent à une 404. "
                "Le catalogue du site a peut-être changé -- relance le "
                "générateur (script.py) pour capturer des sélecteurs à jour."
            )
        page.wait_for_timeout(1500)

        dismiss_cookies(page)

        data = {"url": page.url, "name": None, "price": None, "stock": None}

        try:
            data["name"] = page.title()
        except Exception:
            pass

        import re as _re
        PRICE_RE = _re.compile(r"(€|\$|£)\s?\d+[.,]\d{2}|\d+[.,]\d{2}\s?(€|\$|£)|\d+[.,]\d{2}\s?kr", _re.I)

        def _first_valid_match(selector, max_len, is_valid, max_candidates=10):
            if not selector:
                return None
            try:
                locs = page.locator(selector)
                count = min(locs.count(), max_candidates)
            except Exception:
                return None
            for i in range(count):
                loc = locs.nth(i)
                try:
                    if not loc.is_visible(timeout=1000):
                        continue
                    text = loc.inner_text(timeout=1500).strip()
                except Exception:
                    continue
                if text and len(text) < max_len and is_valid(text):
                    return text
            return None

        data["price"] = _first_valid_match(
            SELECTORS["price"], 40, lambda t: bool(PRICE_RE.search(t))
        )
        if not data["price"]:
            try:
                data["price"] = find_price_generic(page)
            except Exception:
                pass

        data["stock"] = _first_valid_match(
            SELECTORS["stock"], 60, lambda t: any(k in t.lower() for k in STOCK_KEYWORDS)
        )
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
        print("Usage: python scraper_www_petsplace_nl.py \"nom du produit\"")
        sys.exit(1)
    result = scrape(sys.argv[1])
    print("\n=== Résultat ===")
    for k, v in result.items():
        print(f"{k}: {v}")
