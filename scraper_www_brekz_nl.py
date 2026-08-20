"""
Scraper autonome généré automatiquement pour : https://www.brekz.nl
Aucun LLM requis. Basé sur Playwright uniquement.
Utilisation : python scraper_www_brekz_nl.py "nom du produit à chercher"
"""

import sys
from playwright.sync_api import sync_playwright

SITE_URL = "https://www.brekz.nl"
DOMAIN = "www.brekz.nl"
URL_PATTERN = '.html'

SELECTORS = {
    "cookie_button": 'button:has-text("Akkoord en verdergaan")',
    "search_input": '#autocomplete-0-input',
    "search_button": 'button:has-text("Zoeken")',
    "price": '[itemprop="price"]',
    "stock": 'div.col-12.single-product-combination__delivery-promise-wrapper',
}


STOCK_KEYWORDS = [
    "op voorraad", "niet op voorraad", "in stock", "out of stock",
    "en stock", "rupture de stock", "auf lager", "nicht auf lager",
    "en existencia", "agotado",
    "i lager", "ej i lager", "slut i lager", "finns i lager",
    "på lager", "ikke på lager", "varastossa", "ei varastossa",
]


# JS de secours pour fermer une banniere cookies, meme en Shadow DOM
# (Usercentrics, OneTrust, Didomi...). Utilise au runtime si le selecteur
# "cookie_button" capture pendant l'exploration ne marche plus (id
# regenere, bouton deplace, etc.) -- le scraper autonome n'est ainsi plus
# totalement depedant d'un selecteur fige pour cette etape.
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
    """Tente de fermer la banniere cookies : d'abord via le selecteur
    capture pendant l'exploration, puis via la recherche JS en Shadow DOM
    si necessaire ou si la banniere est toujours presente ensuite."""
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
    """Repli générique : cherche le premier élément VISIBLE dont le texte
    ressemble à un prix (symbole monétaire + chiffres), sans dépendre
    d'une valeur figée capturée pendant l'exploration (le prix change
    selon le produit)."""
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
            if (el.children.length > 0) continue;  // élément feuille seulement
            if (el.closest(badAncestors)) continue;  // exclut menu/panier/header
            if (!isVisible(el)) continue;  // exclut sr-only / display:none / etc.
            const text = (el.innerText || el.textContent || '').trim();
            if (text.length < 100 && re.test(text)) return text;
        }
        return null;
    }
    """
    return page.evaluate(js)


def find_stock_generic(page):
    """Repli générique : cherche le premier élément VISIBLE dont le texte
    correspond à un mot-clé de stock connu (multilingue), sans dépendre
    du texte exact capturé pendant l'exploration."""
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
            if (el.closest(badAncestors)) continue;  // exclut menu/panier/header
            if (!isVisible(el)) continue;  // exclut sr-only / display:none / etc.
            const text = (el.innerText || el.textContent || '').trim().toLowerCase();
            if (text.length < 60 && keywords.some(k => text.includes(k))) {
                return (el.innerText || el.textContent || '').trim();
            }
        }
        return null;
    }
    """
    return page.evaluate(js, STOCK_KEYWORDS)


def list_product_links(page):
    """Liste TOUS les liens produits candidats sur la page (pas juste le
    premier), basé sur le pattern d'URL détecté pendant l'exploration.
    Nécessaire pour pouvoir réessayer le candidat suivant si le premier
    s'avère être un lien périmé/promotionnel expiré (404) -- le catalogue
    d'un site change dans le temps, un lien capturé pendant l'exploration
    peut ne plus être valide plus tard."""
    js = """
    (pattern) => {
        const badAncestors = 'nav, header, footer, [class*="menu"], [class*="carousel"], [class*="banner"], [class*="slider"]';
        const links = Array.from(document.querySelectorAll('a[href]'));
        const seen = new Set();
        const results = [];
        for (const a of links) {
            const href = a.getAttribute('href') || '';
            const text = (a.innerText || '').trim();
            if (text.length < 3) continue;
            if (a.closest(badAncestors)) continue;
            const rect = a.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) continue;
            let matches = false;
            if (pattern === '__SLUG__') {
                const slug = href.split('/').filter(Boolean).pop() || '';
                matches = slug.includes('-');
            } else {
                matches = href.includes(pattern);
            }
            if (matches && !seen.has(href)) {
                seen.add(href);
                results.push(href);
            }
        }
        return results;
    }
    """
    return page.evaluate(js, URL_PATTERN)


def click_link_by_href(page, href):
    """Clique le lien correspondant à ce href précis (navigation via le
    routeur JS du site, compatible SPA)."""
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
    "página no encontrada",
]


def is_not_found_page(page) -> bool:
    """Détecte une page d'erreur 404, multilingue, en se basant sur le
    titre ET un court extrait du corps de la page (certains sites gardent
    un titre générique mais affichent le message d'erreur dans le corps)."""
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
            slow_mo=350,  # ralentit chaque action pour bien voir ce qui se passe
            args=["--no-sandbox", "--disable-gpu"],
        )
        page = browser.new_page()

        print(f"→ Ouverture de {SITE_URL} ...")
        page.goto(SITE_URL, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        # Cookies : selecteur capture, PUIS filet de securite Shadow DOM
        # dans tous les cas (au cas ou le selecteur ne suffise pas a
        # faire disparaitre completement la banniere).
        print("→ Fermeture de la bannière cookies ...")
        if dismiss_cookies(page):
            page.wait_for_timeout(500)
        else:
            print("  (pas de bannière cookies visible, on continue)")

        # Recherche
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
            # On presse Entrée DIRECTEMENT sur le champ (search_box.press),
            # pas via le clavier global (page.keyboard.press) : si une
            # tentative de clic a échoué juste avant, le focus peut avoir
            # bougé ailleurs sur la page, et Entrée au clavier global ne
            # soumettrait alors rien silencieusement.
            try:
                search_box.press("Enter")
            except Exception:
                pass
        page.wait_for_timeout(2500)

        # Filet de sécurité : si l'URL n'a pas du tout changé, la
        # recherche n'a probablement pas été soumise (bouton inopérant,
        # focus perdu...) -- on retente une fois avec Entrée sur le champ.
        if page.url.rstrip("/") == SITE_URL.rstrip("/"):
            print("  (recherche non soumise, nouvelle tentative avec Entrée) ...")
            try:
                search_box.press("Enter")
            except Exception:
                pass
            page.wait_for_timeout(3000)
        print(f"  Page de résultats : {page.url}")

        # Produit : on liste TOUS les candidats et on clique le premier,
        # comme un utilisateur (compatible SPA). Si la page atterrit sur
        # une 404 (lien périmé, campagne promo terminée, etc.), on
        # réessaie automatiquement avec le candidat suivant -- jusqu'à 5
        # tentatives -- au lieu de planter sur un lien devenu invalide.
        candidates = list_product_links(page)
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

            # Filet de sécurité si le clic JS n'a pas navigué (site non-SPA)
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

        # Sur certains sites, une nouvelle banniere / popup peut
        # apparaitre sur la fiche produit elle-meme -- on retente donc la
        # fermeture ici aussi, avant de lire prix/stock.
        dismiss_cookies(page)

        data = {"url": page.url, "name": None, "price": None, "stock": None}

        try:
            data["name"] = page.title()
        except Exception:
            pass

        import re as _re
        PRICE_RE = _re.compile(r"(€|\$|£)\s?\d+[.,]\d{2}|\d+[.,]\d{2}\s?(€|\$|£)|\d+[.,]\d{2}\s?kr", _re.I)

        def _first_valid_match(selector, max_len, is_valid, max_candidates=10):
            """Parcourt TOUS les éléments qui matchent le sélecteur (pas
            seulement le premier) et retourne le texte du premier dont le
            contenu est réellement valide. Un sélecteur générique (ex:
            "div.flex") peut matcher plusieurs éléments sans rapport
            (menu, header, panier) selon le site/la page -- se fier
            aveuglément à .first casse silencieusement le scraper. On
            teste donc chaque candidat jusqu'à trouver le bon, ce qui
            rend le scraper fiable sans jamais nécessiter de vérification
            manuelle du sélecteur."""
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
                    # is_visible() exclut le texte présent dans le DOM mais
                    # non affiché à l'écran (spans "sr-only" pour lecteurs
                    # d'écran, données structurées schema.org cachées,
                    # etc.) -- on ne veut que ce qu'un utilisateur voit
                    # réellement, pas n'importe quel texte technique.
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
        print("Usage: python scraper_www_brekz_nl.py \"nom du produit\"")
        sys.exit(1)
    result = scrape(sys.argv[1])
    print("\n=== Résultat ===")
    for k, v in result.items():
        print(f"{k}: {v}")
