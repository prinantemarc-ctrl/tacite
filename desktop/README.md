# Tacite bureau

L’app Mac est une coque Electron. Elle charge la même webapp que le navigateur (`desktop/server.json`, aujourd’hui Render). Postgres, le worker et l’analyse restent sur le serveur.

## Ce qui est partagé

Toute feature de fond vit dans `frontend/` et `backend/`. Un déploiement Render met à jour le web et l’app bureau en même temps, parce que la fenêtre Electron ouvre cette URL.

## Ce qui est natif

`desktop/main.mjs` et `desktop/preload.cjs` exposent `window.tacite` uniquement dans l’app :

- menus Fichier (importer des documents, importer un CSV de médias, actualiser)
- dialogue de fichiers, notifications, pastille du Dock
- connexion MCP vers Cursor

`frontend/src/desktop.ts` est le seul adaptateur. Dans le navigateur ces appels ne font rien et les boutons gardent `<input type="file">`.

Le cache de lecture (`frontend/src/viewCache.ts`, IndexedDB) sert les deux surfaces. Ce n’est pas une copie du corpus.

## Lancer

```bash
cd desktop
npm start
```

`server.json` :

```json
{ "url": "https://tacite-zs2b.onrender.com" }
```

L’app ne démarre plus Docker. Le serveur doit déjà répondre.
