"""
Script : recherche un produit sur un site via browser-use + DeepSeek, PUIS
genere un scraper Python autonome (sans LLM, sans browser-use) specifique
a ce site, base sur les vraies actions effectuees et les vrais selecteurs
CSS captures pendant l'exploration.

Basé sur l'ancienne API browser-use (BrowserConfig / Browser), stable.
Pas de screenshots.

Ce fichier est le point d'entree du projet. Il s'appuie sur :
  - browser_actions.py  : actions custom browser-use (controller)
  - selector_utils.py   : deduction des selecteurs CSS / pattern d'URL
  - scraper_generator.py: template + ecriture du scraper autonome genere

Installation (versions figées pour éviter les incompatibilités d'API) :
    pip install browser-use==0.2.4 langchain-deepseek python-dotenv beautifulsoup4
    playwright install chromium

Configuration :
    Crée un fichier .env avec ta clé API DeepSeek :
        DEEPSEEK_API_KEY=ta_cle_ici

Utilisation :
    python search_product.py
"""

import os
import re
import json
import asyncio
from urllib.parse import urlparse

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek
from browser_use import Agent
from browser_use.browser import BrowserProfile

from browser_actions import controller
from selector_utils import html_to_selector, deduce_url_pattern
from scraper_generator import generate_scraper

load_dotenv()


async def run_agent(url: str, product: str):
    llm = ChatDeepSeek(model="deepseek-chat", api_key=os.getenv("DEEPSEEK_API_KEY"))
    domain = urlparse(url).netloc

    task = f"""
Effectue ces actions sur {url} DANS L'ORDRE EXACT. Ne reviens jamais en
arriere sauf si la page devient blanche (utilise alors robust_goto pour
revenir sur {url} et reprendre a l'etape la plus avancee deja validee).

NAVIGATION : utilise TOUJOURS "robust_goto", jamais "go_to_url".

CAPTURE HTML : n'utilise JAMAIS extract_content pour le outerHTML (il
invente/reformule). Utilise ces actions a la place :
- "capture_and_click" (index) : capture puis clique. Pour cookies/lien produit.
- "capture_and_type" (index, text) : capture puis tape. Pour l'input de recherche.
- "capture_real_html" (index) : capture seule. Pour PRIX/STOCK.
- "dismiss_cookie_banner" : ferme une banniere cookies meme en Shadow DOM,
  des qu'un clic echoue avec "intercepts pointer events".
- "capture_and_click_first_product" : trouve et clique le 1er produit via
  recherche JS directe. A utiliser EN PRIORITE pour l'etape 4.
- "capture_by_text" (text) : capture un element via son texte visible,
  sans index. Pour le STOCK si affiche en texte brut sans index.

ETAPE 1 : "robust_goto" vers {url}. Attends 3s.
ETAPE 2 : Si banniere cookies visible, "capture_and_click" sur "accepter
tout" (ou "dismiss_cookie_banner" si ca echoue). Sinon step1_cookie_html
= chaine vide. IMPORTANT : capture le bouton REELLEMENT clique pour
fermer les cookies, pas un autre element visuellement proche -- verifie
que le texte capture correspond bien a un intitule de consentement
("accepter", "accept", "godkann"...).
ETAPE 3 : Attends 2s. "capture_and_type" sur l'input de recherche avec
"{product}". Attends 1s. Appuie sur Enter. S'il existe un bouton de
soumission de recherche DISTINCT (loupe/icone "rechercher", different du
bouton cookies), capture-le aussi avec "capture_and_click" ou
"capture_real_html" pour step2_button_html. IMPORTANT : ne reutilise
JAMAIS le HTML du bouton cookies (step1_cookie_html) pour
step2_button_html, meme s'il n'y a pas de bouton de recherche distinct --
dans ce cas laisse step2_button_html comme une chaine VIDE. Le bouton
cookies aura de toute facon disparu du DOM apres l'etape 2, cliquer
dessus a nouveau ne sert a rien.
ETAPE 4 : Attends 3s. "capture_and_click_first_product" en priorite. Si
echec, cherche un index manuellement (max 3 actions), sinon laisse vide.
ETAPE 5 : Attends 2s sur la fiche produit. "capture_real_html" sur PRIX.
IMPORTANT : capture l'element qui contient le prix effectivement affiche
a l'ecran (visible), meme s'il s'agit d'un prix "rond" sans decimales
(ex: "699 kr", "45 zl", "1200 Ft") -- ne rejette jamais un prix sous
pretexte qu'il n'a pas de virgule/point decimal, c'est un format valide
dans plusieurs pays. Pour STOCK : index si possible, sinon
"capture_by_text" avec le texte visible du stock.

ETAPE 6 : Termine avec l'action "done" et ce JSON exact (rien d'autre) :
{{{{
    "step1_cookie_html": "...",
    "step2_input_html": "...",
    "step2_button_html": "...",
    "step3_product_html": "...",
    "step3_url_after": "url de la fiche produit",
    "step4_product_name": "...",
    "step4_price": "...",
    "step4_stock": "...",
    "step4_price_html": "...",
    "step4_stock_html": "..."
}}}}
"""

    browser_profile = BrowserProfile(
        headless=False,
        disable_security=True,
        args=["--no-sandbox", "--disable-gpu"],
    )

    agent = Agent(
        task=task,
        llm=llm,
        browser_profile=browser_profile,
        controller=controller,
        use_vision=False,
        max_actions_per_step=1,
    )

    try:
        result = await agent.run(max_steps=35)
    finally:
        if agent.browser_session:
            await agent.browser_session.close()

    text = ""
    if hasattr(result, "final_result"):
        try:
            text = result.final_result() or ""
        except Exception:
            pass
    if not text:
        text = str(result)

    anchor = text.find('"step1_cookie_html"')
    if anchor == -1:
        print("\n⚠️  Pas de JSON exploitable retourné par l'agent. Résultat brut :")
        print(text[:1000])
        return

    start = text.rfind("{", 0, anchor)
    depth, in_str, esc = 0, False, False
    end = None
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        print("\n⚠️  JSON incomplet, impossible de générer le scraper.")
        return

    try:
        data = json.loads(re.sub(r'[\x00-\x1f\x7f]', ' ', text[start:end]))
    except json.JSONDecodeError as e:
        print(f"\n⚠️  Erreur de parsing JSON : {e}")
        return

    print("\n=== Résultat de la recherche ===")
    print(f"Produit : {data.get('step4_product_name')}")
    print(f"Prix    : {data.get('step4_price')}")
    print(f"Stock   : {data.get('step4_stock')}")
    print(f"URL     : {data.get('step3_url_after')}")

    selectors = {
        "cookie": html_to_selector(data.get("step1_cookie_html", ""), is_button=True),
        "search_input": html_to_selector(data.get("step2_input_html", "")),
        "search_button": html_to_selector(data.get("step2_button_html", ""), is_button=True),
        "price": html_to_selector(data.get("step4_price_html", ""), allow_text_fallback=False),
        "stock": html_to_selector(data.get("step4_stock_html", ""), allow_text_fallback=False),
        "url_pattern": deduce_url_pattern(data.get("step3_url_after", ""), domain),
    }

    if selectors["search_button"] and selectors["search_button"] == selectors["cookie"]:
        print(
            "\n⚠️  Sélecteur 'search_button' identique à 'cookie' (probable "
            "erreur de capture) -> ignoré, le scraper utilisera Enter à la place."
        )
        selectors["search_button"] = ""

    print("\n=== Sélecteurs déduits ===")
    for k, v in selectors.items():
        print(f"  {k}: {v}")

    if not selectors["search_input"]:
        print("\n⚠️  Pas de sélecteur pour la recherche : le scraper généré ne fonctionnera pas correctement.")
        return

    filepath = generate_scraper(url, domain, selectors)
    print(f"\n✅ Scraper généré : {filepath}")
    print(f"   Utilisation ensuite (sans LLM) : python {filepath} \"nom du produit\"")


def main():
    print("=" * 50)
    print("  RECHERCHE DE PRODUIT + GÉNÉRATION DE SCRAPER")
    print("=" * 50)
    site_url = input("\nURL du site : ").strip()
    product_name = input("Produit à chercher : ").strip()
    if not site_url or not product_name:
        print("Erreur : l'URL du site et le nom du produit sont obligatoires.")
        return
    print(f"\nRecherche de '{product_name}' sur {site_url}...")
    print("-" * 50)
    asyncio.run(run_agent(site_url, product_name))


if __name__ == "__main__":
    main()