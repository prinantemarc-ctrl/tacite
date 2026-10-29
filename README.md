# Tacite — Plateforme d'intelligence presse & recommandation d'influence

Tacite capture la presse (RSS + scraping), analyse chaque article par LLM
(cadrage sur 12 axes, sources, ton, entités), profile les journalistes
(fixations, vulnérabilités, accessibilité) et les médias (classification
réelle vs officielle, score d'influence), puis recommande des actions
d'influence adaptées à chaque client.

## Démarrage rapide

1. Renseigner `.env` (voir `.env.example`) : `LLM_API_KEY` suffit avec Docker.
2. Lancer la stack :

```bash
docker compose up -d --build
```

3. Ouvrir http://localhost:5173 — l'API est sur http://localhost:8000 (docs : `/docs`).

Au premier démarrage, une dizaine de médias français sont pré-enregistrés.
Le worker ingère les flux RSS toutes les 15 minutes, analyse les articles en
continu, recalcule les profils journalistes chaque jour et les profils
médias / scores d'influence chaque semaine.

## Stack

- **Backend** : FastAPI + SQLAlchemy, PostgreSQL + pgvector
- **Analyse** : Aleria (`https://inference.aleria.com/v1`, modèle `aleria`), sentence-transformers (embeddings locaux), spaCy (NER local)
- **Worker** : boucle de tâches planifiées (ingestion, analyse, profils, recommandations)
- **Frontend** : React + Vite + Tailwind + Recharts, thème sombre, UI en français

## Variables d'environnement

| Variable | Requis | Description |
|---|---|---|
| `DATABASE_URL` | oui | PostgreSQL avec extension pgvector |
| `LLM_API_KEY` | oui | Clé d'API Aleria |
| `LLM_BASE_URL` | oui | `https://inference.aleria.com/v1` |

Tout le reste (fréquences d'ingestion, poids du score d'influence, seuils,
modèles LLM) se configure dans la page Paramètres (stocké en base).
