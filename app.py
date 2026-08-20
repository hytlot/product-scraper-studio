"""
Interface graphique Streamlit pour le projet "search_product".

Deux modes disponibles :
  1. Générer un scraper : lance l'agent browser-use + DeepSeek sur une URL
     donnée, explore le site pour un produit test, puis génère un fichier
     scraper_<domaine>.py autonome (sans LLM) dans le dossier courant.
  2. Utiliser un scraper existant : liste les fichiers scraper_*.py déjà
     générés, permet de choisir un site et de lancer une recherche de
     produit avec ce scraper (sans LLM, juste Playwright).

Prérequis :
    - Le script original doit être sauvegardé sous le nom "search_product.py"
      dans le même dossier que ce fichier app.py.
    - pip install streamlit browser-use==0.2.4 langchain-deepseek python-dotenv beautifulsoup4 playwright
    - playwright install chromium
    - Un fichier .env avec DEEPSEEK_API_KEY=... à la racine du projet.

Lancement :
    streamlit run app.py
"""

import asyncio
import glob
import importlib.util
import io
import os
import sys
import traceback
from contextlib import redirect_stdout
from urllib.parse import urlparse

import streamlit as st

# ---------------------------------------------------------------------------
# Import du script original.
# Accepte indifféremment "search_product.py" ou "script.py" à côté de app.py,
# pour éviter les erreurs de nommage.
# ---------------------------------------------------------------------------
sp = None
_import_error = None
for _module_name in ("search_product", "script"):
    try:
        sp = __import__(_module_name)
        break
    except ImportError as e:
        _import_error = e

st.set_page_config(page_title="Product Scraper Studio", page_icon="🛒", layout="wide")

st.title("🛒 Product Scraper Studio")
st.caption(
    "Génère un scraper autonome pour un site e-commerce, puis réutilise-le "
    "sans LLM pour chercher n'importe quel produit sur ce même site."
)

if sp is None:
    st.error(
        "Ni `search_product.py` ni `script.py` n'ont été trouvés dans le "
        f"dossier de l'application (erreur : {_import_error}). Place ton "
        "script original à côté de `app.py` puis relance Streamlit."
    )
    st.stop()

# --- Clé API DeepSeek -------------------------------------------------------
# On tente d'abord le .env (déjà chargé par le script importé via load_dotenv()),
# mais on force explicitement une recherche du fichier .env dans le dossier
# courant ET le dossier de app.py, au cas où Streamlit soit lancé depuis un
# autre répertoire de travail. On propose aussi une saisie manuelle en secours.
try:
    from dotenv import load_dotenv, find_dotenv
    _candidates = []
    _cwd_dotenv = find_dotenv(usecwd=True)
    if _cwd_dotenv:
        _candidates.append(_cwd_dotenv)
    if getattr(sp, "__file__", None):
        _script_dotenv = os.path.join(os.path.dirname(os.path.abspath(sp.__file__)), ".env")
        _candidates.append(_script_dotenv)
    _app_dotenv = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    _candidates.append(_app_dotenv)
    for _path in _candidates:
        if _path and os.path.exists(_path):
            load_dotenv(_path, override=False)
            break
except ImportError:
    pass

with st.sidebar:
    st.header("🔑 Configuration")
    manual_key = st.text_input(
        "Clé API DeepSeek",
        value=os.getenv("DEEPSEEK_API_KEY", ""),
        type="password",
        help="Nécessaire uniquement pour générer un NOUVEAU scraper. "
             "Pas besoin pour réutiliser un scraper déjà généré.",
    )
    if manual_key:
        os.environ["DEEPSEEK_API_KEY"] = manual_key

if not os.getenv("DEEPSEEK_API_KEY"):
    st.warning(
        "⚠️ Aucune clé `DEEPSEEK_API_KEY` détectée. Renseigne-la dans la "
        "barre latérale, ou crée un fichier `.env` (avec "
        "`DEEPSEEK_API_KEY=ta_cle`) dans le dossier où tu lances "
        "`streamlit run app.py`. Pas nécessaire pour réutiliser un scraper "
        "déjà généré."
    )

tab_generate, tab_use = st.tabs(["🧠 Générer un scraper", "⚡ Utiliser un scraper existant"])


class LiveLogWriter(io.StringIO):
    """StringIO qui pousse chaque écriture vers un placeholder Streamlit,
    pour afficher les logs au fur et à mesure plutôt qu'en un seul bloc."""

    def __init__(self, placeholder):
        super().__init__()
        self.placeholder = placeholder
        self.buffer_text = ""

    def write(self, s):
        self.buffer_text += s
        self.placeholder.code(self.buffer_text[-4000:], language="text")
        return super().write(s)


# ---------------------------------------------------------------------------
# Onglet 1 : génération d'un nouveau scraper via l'agent LLM
# ---------------------------------------------------------------------------
with tab_generate:
    st.subheader("Explorer un site et générer son scraper")
    st.write(
        "L'agent va ouvrir le site, accepter les cookies, chercher le "
        "produit indiqué, ouvrir sa fiche, capturer les vrais sélecteurs "
        "CSS, puis écrire un fichier `scraper_<domaine>.py` réutilisable "
        "sans LLM."
    )

    col1, col2 = st.columns(2)
    with col1:
        site_url = st.text_input("URL du site", placeholder="https://www.exemple.com")
    with col2:
        product_name = st.text_input("Produit à chercher (exploration)", placeholder="croquettes chat 4kg")

    headless_note = st.checkbox(
        "J'ai bien un environnement graphique disponible (le navigateur s'ouvre en mode visible)",
        value=True,
        help="Le script original lance Chromium avec headless=False. "
             "Sur un serveur sans affichage, l'exploration échouera.",
    )

    launch = st.button("🚀 Lancer l'exploration et générer le scraper", type="primary", use_container_width=True)

    log_placeholder = st.empty()
    result_container = st.container()

    if launch:
        if not site_url or not product_name:
            st.error("Merci de renseigner l'URL du site ET un nom de produit.")
        elif not headless_note:
            st.error("Active un environnement graphique avant de lancer l'exploration.")
        else:
            domain = urlparse(site_url).netloc
            expected_filename = f"scraper_{__import__('re').sub(r'[^a-zA-Z0-9]', '_', domain)}.py"
            existing_before = set(glob.glob("scraper_*.py"))

            writer = LiveLogWriter(log_placeholder)
            with st.spinner("Exploration du site en cours (le navigateur va s'ouvrir)..."):
                try:
                    with redirect_stdout(writer):
                        asyncio.run(sp.run_agent(site_url, product_name))
                except Exception as e:
                    result_container.error(f"❌ Erreur pendant l'exploration : {e}")
                    result_container.code(traceback.format_exc(), language="text")
                else:
                    existing_after = set(glob.glob("scraper_*.py"))
                    new_files = existing_after - existing_before
                    generated = new_files.pop() if new_files else (
                        expected_filename if os.path.exists(expected_filename) else None
                    )
                    if generated:
                        result_container.success(f"✅ Scraper généré : `{generated}`")
                        with open(generated, "r", encoding="utf-8") as f:
                            code_content = f.read()
                        with result_container.expander("Voir le code généré"):
                            st.code(code_content, language="python")
                        result_container.download_button(
                            "⬇️ Télécharger le scraper",
                            data=code_content,
                            file_name=generated,
                            mime="text/x-python",
                            use_container_width=True,
                        )
                    else:
                        result_container.warning(
                            "L'exploration s'est terminée mais aucun fichier scraper n'a été "
                            "détecté. Regarde les logs ci-dessus pour comprendre pourquoi "
                            "(sélecteurs manquants, JSON invalide, etc.)."
                        )

# ---------------------------------------------------------------------------
# Onglet 2 : réutilisation d'un scraper déjà généré (sans LLM)
# ---------------------------------------------------------------------------
with tab_use:
    st.subheader("Réutiliser un scraper déjà généré")

    scraper_files = sorted(glob.glob("scraper_*.py"))
    if not scraper_files:
        st.info("Aucun scraper généré pour l'instant. Passe par l'onglet précédent pour en créer un.")
    else:
        chosen_file = st.selectbox("Scraper à utiliser", scraper_files)
        product_query = st.text_input("Produit à chercher", key="reuse_product")
        run_it = st.button("🔍 Lancer la recherche", type="primary", use_container_width=True)

        if run_it:
            if not product_query:
                st.error("Merci d'indiquer un nom de produit.")
            else:
                module_name = os.path.splitext(chosen_file)[0]
                spec = importlib.util.spec_from_file_location(module_name, chosen_file)
                mod = importlib.util.module_from_spec(spec)
                writer = LiveLogWriter(st.empty())
                with st.spinner("Recherche en cours (le navigateur va s'ouvrir)..."):
                    try:
                        spec.loader.exec_module(mod)
                        with redirect_stdout(writer):
                            data = mod.scrape(product_query)
                    except Exception as e:
                        st.error(f"❌ Erreur pendant le scraping : {e}")
                        st.code(traceback.format_exc(), language="text")
                    else:
                        st.success("✅ Résultat trouvé")
                        c1, c2, c3 = st.columns(3)
                        c1.metric("Prix", data.get("price") or "Inconnu")
                        c2.metric("Stock", data.get("stock") or "Inconnu")
                        c3.write(f"**URL**  \n{data.get('url', '')}")
                        st.write(f"**Nom produit :** {data.get('name') or 'Inconnu'}")
                        st.json(data)

st.divider()
st.caption(
    "Astuce : place ce fichier `app.py` et `search_product.py` dans le même "
    "dossier, puis lance `streamlit run app.py`. Les fichiers "
    "`scraper_*.py` générés apparaissent automatiquement dans l'onglet "
    "« Utiliser un scraper existant »."
)