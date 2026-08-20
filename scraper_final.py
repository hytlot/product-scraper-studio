"""
scraper_final.py — généré automatiquement, SANS LLM.
Cherche UN produit précis (donné en argument) sur https://www.petsplace.nl et
affiche/sauvegarde son nom, son prix et son stock.
Basé sur Playwright pur (le site et/ou sa recherche nécessitent du
JavaScript), sans agent IA. Ferme automatiquement le popup de cookies
s'il y en a un.
"""
import csv
import json
import sys
from urllib.parse import quote_plus, urljoin
from playwright.sync_api import sync_playwright

URL_SITE = 'https://www.petsplace.nl'

POPUP_COOKIES_PRESENT = True
SELECTEUR_BOUTON_COOKIES = '#btn-cookie-allow'

URL_RECHERCHE_MOTIF = 'https://www.petsplace.nl/catalogsearch/result/?q={q}'  # doit contenir {q}
SELECTEUR_CHAMP_RECHERCHE = 'input#search'
SELECTEUR_PREMIER_RESULTAT = ''

SELECTEUR_NOM = 'h1.page-title span.base'
SELECTEUR_PRIX = 'span.price-wrapper span.price'
SELECTEUR_DEVISE = ''
SELECTEUR_STOCK = 'div.stock.available span'


def fermer_popup_cookies(page):
    if not POPUP_COOKIES_PRESENT or not SELECTEUR_BOUTON_COOKIES:
        return
    try:
        bouton = page.wait_for_selector(SELECTEUR_BOUTON_COOKIES, timeout=4000)
        if bouton:
            bouton.click()
            page.wait_for_timeout(400)
    except Exception:
        pass  # pas grave si le popup n'apparaît pas cette fois


def chercher_produit(page, nom_produit: str) -> str | None:
    if URL_RECHERCHE_MOTIF:
        url_recherche = URL_RECHERCHE_MOTIF.replace("{q}", quote_plus(nom_produit))
        page.goto(url_recherche, wait_until="networkidle")
        fermer_popup_cookies(page)
    elif SELECTEUR_CHAMP_RECHERCHE:
        page.goto(URL_SITE, wait_until="networkidle")
        fermer_popup_cookies(page)
        champ = page.query_selector(SELECTEUR_CHAMP_RECHERCHE)
        if not champ:
            print("❌ Champ de recherche introuvable sur la page.")
            return None
        champ.fill(nom_produit)
        champ.press("Enter")
        page.wait_for_load_state("networkidle")
    else:
        print("❌ Aucun mécanisme de recherche connu pour ce site.")
        return None

    if not SELECTEUR_PREMIER_RESULTAT:
        print("❌ Aucun sélecteur de résultat connu pour ce site.")
        return None

    lien = page.query_selector(SELECTEUR_PREMIER_RESULTAT)
    if not lien:
        return None
    href = lien.get_attribute("href")
    return urljoin(page.url, href) if href else None


def scraper_page(page, url: str) -> dict:
    page.goto(url, wait_until="networkidle")
    fermer_popup_cookies(page)

    def texte(selecteur):
        if not selecteur:
            return None
        el = page.query_selector(selecteur)
        return el.inner_text().strip() if el else None

    return {
        "url": url,
        "nom_produit": texte(SELECTEUR_NOM),
        "prix": texte(SELECTEUR_PRIX),
        "devise": texte(SELECTEUR_DEVISE),
        "stock": texte(SELECTEUR_STOCK),
    }


def main():
    if len(sys.argv) > 1:
        nom_produit = " ".join(sys.argv[1:])
    else:
        nom_produit = input("Nom du produit à chercher : ").strip()

    if not nom_produit:
        print("❌ Aucun nom de produit fourni.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(URL_SITE, wait_until="networkidle")
        fermer_popup_cookies(page)

        print(f"🔎 Recherche de '{nom_produit}' sur {URL_SITE}...")
        url_produit = chercher_produit(page, nom_produit)
        if not url_produit:
            print(f"❌ Aucun produit trouvé pour '{nom_produit}'.")
            browser.close()
            return

        print(f"📄 Fiche produit trouvée : {url_produit}")
        produit = scraper_page(page, url_produit)

        browser.close()

    print(json.dumps(produit, indent=2, ensure_ascii=False))

    with open("produit.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=produit.keys())
        writer.writeheader()
        writer.writerow(produit)
    print("\n✅ Résultat sauvegardé dans produit.csv")


if __name__ == "__main__":
    main()
