# chart-mcp

Serveur **MCP** qui transforme des données tabulaires en **graphique interactif auto-typé**, rendu via le standard **[mcp-ui](https://mcpui.dev)**.

L'IA appelle un seul outil, `render_chart`, en passant les données ; le serveur choisit le bon type de graphique et renvoie une UI à **deux onglets** :

- **📊 Graphique** — ECharts interactif (toggle légende, zoom, sélection au lasso).
- **▦ Données** — tableau exportable en **CSV** et **Excel** via les icônes de la barre d'outils.

## Sélection automatique du type de graphique

Quand `chart_type="auto"` (défaut), les règles déterministes sont :

| Données | Type choisi |
|---|---|
| Axe date/temps + 1 série numérique | aire (`area`) |
| Axe date/temps + ≥2 séries | courbe (`line`) |
| **2 colonnes catégorielles + 1 mesure** | **barres groupées (`grouped_bar`)** — la 2ᵉ catégorielle devient les séries |
| Catégoriel + 1 numérique, 2–6 catégories, valeurs ≥0 | camembert (`pie`) |
| Catégoriel (autres cas) | barres (`bar`) |
| Deux colonnes numériques | nuage de points (`scatter`) |
| Aucun axe catégoriel/temporel | histogramme (`histogram`) |

Chaque choix est accompagné d'un texte `reasoning` affiché sous le titre. On peut forcer le type (`chart_type="bar"`), épingler les colonnes (`x`, `y`, `group_by`) et empiler (`stacked=true`).

### Barres groupées et empilées

Sur une forme « longue » (`{region, produit, ventes}`), une 2ᵉ colonne catégorielle était auparavant ignorée. Désormais elle est détectée automatiquement et pivote en séries : chaque valeur de `group_by` devient une barre, comparée à travers les catégories de `x` (la mesure est **sommée** par cellule). `stacked=true` (ou `chart_type="stacked_bar"`) empile au lieu de juxtaposer. La sélection (clic / lasso) sur une barre pivotée surligne les lignes correspondant au couple (catégorie, groupe).

## Sélection dynamique

Sur les graphes cartésiens (barres / courbes / aire / nuage), la sélection au lasso (*brush*) et le clic surlignent les lignes correspondantes dans le tableau. Un bouton **« Envoyer la sélection à l'assistant »** émet une action mcp-ui `prompt` (via `postMessage`) avec l'échantillon sélectionné, permettant à l'hôte de poursuivre la conversation sur ce sous-ensemble.

## Architecture

```
chart-mcp/
├── Dockerfile / docker-compose.yml
├── pyproject.toml / requirements.txt
├── src/chart_mcp/
│   ├── server.py          # serveur FastMCP + outil render_chart + route /assets
│   ├── data_utils.py      # records -> DataFrame, détection du type de colonne
│   ├── chart_selector.py  # règles de choix du type de graphique
│   ├── chart_options.py   # construction de l'option ECharts (testable, sans navigateur)
│   ├── data_reduce.py     # plafond de lignes, top-N, résumé texte
│   ├── assets.py          # résolution CDN / inline / self-hosted des JS
│   ├── ui_builder.py      # assemblage du HTML (injection JSON sûre pour <script>)
│   ├── template.py        # gabarit HTML/JS des deux onglets
│   └── vendor/            # echarts.min.js + xlsx.full.min.js (servis en local)
└── tests/                 # un fichier de tests par fonctionnalité
```

La décision *et* la configuration du graphique sont faites côté Python (l'option ECharts est sérialisée en JSON et le front fait juste `chart.setOption(option)`), ce qui rend toute la logique testable sans navigateur.

## Installation & exécution

```bash
pip install -e .            # ou: pip install -r requirements.txt

# Local (clients en sous-processus) — transport stdio
chart-mcp

# Distant (hôtes web) — HTTP streamable, endpoint http://HOST:8000/mcp
chart-mcp --transport http --host 0.0.0.0 --port 8000
```

### Docker

```bash
docker compose up --build
# expose le endpoint streamable HTTP sur http://localhost:8000/mcp
```

### Intégration LibreChat

Déclarer le serveur dans `librechat.yaml` (transport `streamable-http`) :

```yaml
mcpServers:
  chart:
    type: streamable-http
    url: http://chart-mcp:8000/mcp
```

> LibreChat fait partie des hôtes qui supportent le rendu mcp-ui. En stdio, pointer la commande vers `chart-mcp`.

## Outil `render_chart`

| Paramètre | Type | Description |
|---|---|---|
| `data` | `list[dict]` (requis) | Lignes du jeu de données, ex. `[{"month":"Jan","sales":120}]`. |
| `title` | `str` | Titre affiché au-dessus du graphique. |
| `chart_type` | `str` | `auto` (défaut) ou `bar`/`grouped_bar`/`stacked_bar`/`line`/`area`/`scatter`/`pie`/`histogram`. |
| `x` | `str?` | Colonne d'axe x / catégorie / label de camembert. |
| `y` | `list[str]?` | Colonnes numériques à tracer. |
| `group_by` | `str?` | 2ᵉ colonne catégorielle pour barres groupées/empilées (inférée si absente). |
| `stacked` | `bool` | Empile les séries au lieu de les juxtaposer. |
| `max_rows` | `int` | Plafond de lignes embarquées (défaut 5000). Au-delà, troncature avec avertissement. |
| `top_n` | `int?` | Garde les N plus grandes catégories, regroupe le reste dans « Autres » (off par défaut). |

Retourne **deux blocs** : un résumé texte (lisible par le modèle même si l'hôte ne rend pas mcp-ui) puis la `UIResource` mcp-ui (`rawHtml`, encodée en `blob`).

## Chargement des dépendances JS (assets)

Le graphique tourne dans l'iframe sandboxée de l'hôte : les `<script>` doivent pointer vers une URL absolue atteignable. La variable `CHART_MCP_ASSETS` contrôle cela :

- `cdn` (défaut) — jsDelivr. Zéro config, nécessite un accès internet sortant.
- `inline` — ECharts/SheetJS embarqués directement dans la page. Totalement autonome (air-gap), payload plus lourd (~1,6 Mo).
- une URL/base, ex. `http://chart-mcp:8000/assets` — les deux fichiers (versionnés dans le package sous `vendor/`) sont référencés depuis là. En transport HTTP, le serveur les héberge lui-même via sa route `GET /assets/{filename}`.

## Garde-fous pour gros volumes

- **Plafond de lignes** (`max_rows`, défaut 5000) : le graphique et le tableau partagent les mêmes lignes (la sélection reste fiable). Au-delà, troncature + bandeau d'avertissement + note dans le résumé.
- **Top-N** (`top_n`, optionnel) : pour les graphes catégoriels, garde les N plus grosses catégories et agrège le reste dans « Autres ». Vue de synthèse : le mapping sélection→ligne est alors désactivé.
- **Tableau virtualisé** : rendu progressif par tranches de 200 lignes (IntersectionObserver) pour borner le DOM.

## Tests

```bash
pytest        # 93 tests, un fichier par fonctionnalité
```

- `test_data_utils.py` — parsing + détection de type de colonne
- `test_chart_selector.py` — règles de sélection (dont barres groupées/empilées)
- `test_chart_options.py` — génération de l'option ECharts
- `test_data_reduce.py` — plafond de lignes, top-N, résumé
- `test_assets.py` — résolution CDN / inline / self-hosted
- `test_ui_builder.py` — assemblage HTML + injection sûre
- `test_server.py` — validation Pydantic, sortie (texte + ressource), réductions

## Notes

- **Assets** : par défaut chargés depuis `cdn.jsdelivr.net`, mais entièrement configurables (voir `CHART_MCP_ASSETS` ci-dessus) — inline ou auto-hébergés pour un environnement sans accès internet. L'iframe mcp-ui est sandboxée (`allow-scripts`).
- **Téléchargement** : le téléchargement par ancre nécessite que l'hôte autorise `allow-downloads` sur l'iframe. À défaut, le fichier est transmis à l'hôte via une action mcp-ui `link` (data-URL) en repli.
- Export Excel **réel** (`.xlsx`) via SheetJS ; le CSV est généré nativement (BOM UTF-8 pour Excel).
- **En-tête Host / erreur 421** : en transport HTTP, le SDK MCP active une protection anti DNS-rebinding qui ne tolère que `localhost` par défaut. Si le serveur est joint via un vrai nom d'hôte, déclarer celui-ci dans `CHART_MCP_ALLOWED_HOSTS` (ex. `applflwlrec001.chronodrive.local:*`, `:*` = tout port ; `*` désactive la vérification). Sinon les requêtes sont rejetées en `421 Misdirected Request` (« Invalid Host header »). Le chemin de l'endpoint (`/mcp` par défaut) est ajustable via `CHART_MCP_HTTP_PATH`.
