"""
Fonctions utilitaires pour transformer un outerHTML capture pendant
l'exploration en un selecteur CSS stable, et pour deduire le pattern
d'URL des pages produit du site (ex: "/p/", "__SLUG__", "__TRAILING_P__").
"""

import re

from bs4 import BeautifulSoup


def _escape_css(cls: str) -> str:
    return re.sub(r'([:/.\[\]()%])', r'\\\1', cls)


def _looks_dynamic(value: str) -> bool:
    return bool(re.search(r'\d', value or ""))


def html_to_selector(html: str, allow_text_fallback: bool = True, is_button: bool = False) -> str:
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        el = soup.find()
        if not el:
            return ""

        def _text_selector():
            text = el.get_text(strip=True)
            if text and len(text) < 40:
                return f'{el.name}:has-text("{text}")'
            return ""

        if is_button:
            sel = _text_selector()
            if sel:
                return sel

        if el.get("id"):
            id_val = el["id"]
            looks_dynamic = bool(re.search(r'[0-9a-f]{16,}', id_val, re.I) or re.search(r'\d{6,}', id_val))
            if not looks_dynamic:
                return f'#{_escape_css(id_val)}'
        if el.get("itemprop"):
            return f'[itemprop="{el["itemprop"]}"]'
        if el.get("data-testid"):
            return f'[data-testid="{el["data-testid"]}"]'
        if el.get("aria-label"):
            aria_val = el["aria-label"]
            if not _looks_dynamic(aria_val):
                return f'{el.name}[aria-label="{aria_val}"]'
        if el.get("name"):
            return f'{el.name}[name="{el["name"]}"]'
        if el.get("type") and el.name in ["input", "button"]:
            return f'{el.name}[type="{el["type"]}"]'

        all_classes = el.get("class", [])
        stable = [c for c in all_classes if not c.startswith("css-") and not re.match(r'^[a-z]{1,2}\d+', c) and ":" not in c]
        css_hash = [c for c in all_classes if c.startswith("css-")]

        # Priorite aux classes d'ETAT (is-selected, active, current...) :
        # sur les pages avec plusieurs variantes similaires (tailles,
        # couleurs...), c'est souvent la SEULE classe qui distingue
        # l'element reellement choisi des autres. Sans cette priorite, un
        # slice naif stable[:2] peut la perdre si d'autres classes
        # generiques (partagees par TOUTES les variantes) apparaissent
        # avant elle dans l'attribut class -- le selecteur genere matche
        # alors n'importe laquelle des variantes au lieu de la bonne (bug
        # observe sur kiwoko.com : le prix retourne etait celui d'un
        # variant 4kg au lieu du 9kg reellement capture pendant
        # l'exploration).
        state_pattern = re.compile(r'^(is-)?(selected|active|current|chosen|checked)', re.I)
        state_classes = [c for c in stable if state_pattern.match(c)]
        other_classes = [c for c in stable if not state_pattern.match(c)]
        stable = state_classes + other_classes

        if stable and css_hash:
            return f'{el.name}.{_escape_css(stable[0])}.{_escape_css(css_hash[0])}'
        if stable:
            return f'{el.name}.{".".join(_escape_css(c) for c in stable[:3])}'
        if css_hash:
            return f'{el.name}.{".".join(_escape_css(c) for c in css_hash[:2])}'

        if allow_text_fallback:
            sel = _text_selector()
            if sel:
                return sel
        return ""
    except Exception:
        return ""


def deduce_url_pattern(url_after: str, domain: str) -> str:
    if not url_after:
        return "__SLUG__"
    for pattern in ["/p/", "/products/", "/product/", "/produkt/", "/produit/", "/artikel/", "/item/", "/katalog/"]:
        if pattern in url_after:
            return pattern
    path = url_after.replace(f"https://{domain}", "").replace(f"http://{domain}", "")
    path_no_query = path.split("?", 1)[0].split("#", 1)[0]
    if path_no_query.endswith(".html"):
        return ".html"
    parts = [p for p in path_no_query.split("/") if p]
    if parts and parts[-1] == "p":
        return "__TRAILING_P__"
    return "__SLUG__"