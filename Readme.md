# Product Scraper Studio

Génère un scraper Python **autonome** (sans LLM, sans navigateur piloté par
IA) pour n'importe quel site e-commerce, à partir d'une seule exploration
guidée par un agent [browser-use](https://github.com/browser-use/browser-use)
+ DeepSeek. Une fois le scraper généré, il fonctionne **sans clé API**,
uniquement avec Playwright.

## Structure du projet

```
.
├── app.py                  # Interface graphique Streamlit (point d'entrée principal)
├── search_product.py       # Agent d'exploration (LLM) : navigue, capture les sélecteurs, lance la génération
├── browser_actions.py      # Actions custom browser-use (clic, capture HTML, gestion cookies...)
├── selector_utils.py       # Déduction des sélecteurs CSS et du pattern d'URL produit
├── scraper_generator.py    # Template + écriture du scraper autonome généré
├── requirements.txt        # Dépendances Python
├── .env.example             # Modèle de fichier de configuration (clé API)
└── scraper_<domaine>.py    # Scrapers générés automatiquement (un par site exploré)
```

Tous ces fichiers doivent rester **dans le même dossier** : `app.py` importe
`search_product`, qui importe à son tour `browser_actions`,
`selector_utils` et `scraper_generator`.

## Installation

```bash
pip install -r requirements.txt
playwright install chromium
```

## Configuration

1. Copie `.env.example` en `.env` (même dossier).
2. Remplace la valeur par ta vraie clé API DeepSeek :

```
DEEPSEEK_API_KEY=ta_cle_ici
```

La clé API n'est nécessaire que pour **générer** un nouveau scraper
(exploration guidée par le LLM). Une fois un scraper généré, il fonctionne
sans clé API.

## Utilisation

### Via l'interface graphique (recommandé)

```bash
streamlit run app.py
```

Deux onglets :

- **🧠 Générer un scraper** : indique l'URL d'un site et un produit test.
  L'agent explore le site (le navigateur s'ouvre en mode visible), capture
  les vrais sélecteurs CSS, et écrit un fichier `scraper_<domaine>.py`
  réutilisable sans LLM.
- **⚡ Utiliser un scraper existant** : liste tous les fichiers
  `scraper_*.py` déjà présents dans le dossier et permet de lancer une
  recherche de produit avec l'un d'eux, sans IA.

### En ligne de commande

Générer un nouveau scraper :

```bash
python search_product.py
```

Utiliser un scraper déjà généré (sans LLM) :

```bash
python scraper_<domaine>.py "nom du produit à chercher"
```

