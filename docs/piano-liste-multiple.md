# Piano: liste multiple con nome per utente

## Obiettivo

Un utente può creare più liste desideri, ognuna con un proprio nome (es. "Natale", "Compleanno", "Viaggio in Giappone"), invece dell'attuale modello rigido di una lista per utente.

## Decisioni di design

| Decisione | Scelta |
|---|---|
| Link pubblico | Uno per lista, ognuna con il suo token rigenerabile |
| Directory pubblica | Ogni lista è una voce separata |
| Ultima lista | Non eliminabile — ne resta sempre almeno una per utente |
| Claim management | Per-utente, vale per tutte le liste |
| Creazione/rinomina | Inline nella toolbar della pagina wishlist |
| URL della lista attiva | Codice univoco e non intuibile (`/?list=<code>`), non numeri ordinali |

## 1. Modello dati

```
User 1 ──< Wishlist >── Gift
```

### Nuova tabella `wishlist`

- `id` — PK
- `owner_id` — FK a `user.id`
- `name` — String(100), obbligatorio
- `share_token` — String(64), unico, autogenerato, **rigenerabile** (è il link pubblico)
- `code` — String(64), unico, autogenerato, **stabile per sempre** (identifica la lista nell'URL owner)

### Perché due token separati

- `share_token`: il link pubblico (`/list/<token>`); se rigenerato (es. perché divulgato), i vecchi link smettono di funzionare
- `code`: l'URL della pagina owner (`/?list=<code>`); non cambia mai, quindi segnalibri e cronologia continuano a funzionare; non essendo intuibile, un altro utente loggato non può sondare le liste altrui

### Gift

- Aggiunto `wishlist_id` (FK a `wishlist.id`, obbligatorio)
- `owner_id` **resta** denormalizzato: le verifiche di proprietà, la pagina "Received" e i claim non cambiano

### User

- Colonna `list_name` **rimossa**: il nome vive nella lista

## 2. Backend

| File | Cambio |
|---|---|
| `backend/models.py` | Modello `Wishlist`, `Gift.wishlist_id`, rimozione `list_name` da User |
| `backend/routes/lists.py` **(nuovo)** | `GET/POST /api/lists` · `PUT/DELETE /api/lists/<id>` (403 se è l'ultima) · `POST /api/lists/<id>/share-token` |
| `backend/routes/items.py` | `GET /api/items?list_id=N` (senza param = tutti i regali dell'utente → ReceivedPage invariata); `POST /api/items` accetta `list_id` |
| `backend/routes/public.py` | Lookup token → `Wishlist`; directory itera le liste; **stesse forme di risposta di oggi** → pagine pubbliche invariate |
| `backend/routes/auth.py` | Rimozione `list_name` da update_account; rimozione del vecchio endpoint `/api/account/share-token` |
| `backend/routes/admin.py` | `create_user` e `bootstrap-db` creano automaticamente la lista di default (`"{username}'s wishlist"`) per mantenere l'invariante "almeno una lista"; rimozione `list_name` da update_user |
| `backend/app.py` | Registrazione del nuovo blueprint `lists_bp` |

## 3. Migrazione Alembic

1. Crea la tabella `wishlist` (con `share_token` e `code`)
2. Per ogni utente esistente: crea una lista col nome attuale (`list_name` o default calcolato `{username}'s wishlist`)
3. Riassegna tutti i regali alla lista del loro proprietario
4. Rimuove la colonna `user.list_name`
5. **Reversibile**: il downgrade ricostruisce `user.list_name` dalla prima lista di ogni utente — necessario perché i test eseguono upgrade/downgrade reali

## 4. Frontend

| File | Cambio |
|---|---|
| `frontend/src/pages/WishlistPage.jsx` | **Il grosso.** Toolbar: `[ Natale ▾ ]  [+]  [✏️]  [🗑]  …  [+ Nuovo regalo]`. Il selettore liste sostituisce l'attuale `<h2>` (stilizzato come titolo). **+**: al posto del selettore appare un input inline; Invio crea la lista e la rende attiva, Esc annulla. **✏️**: stesso meccanismo, precompilato col nome attuale. **🗑**: conferma ("cancellerà anche i suoi N regali, compresi i ricevuti"); se è l'ultima lista → errore. URL: `/?list=<code>` con replace alla selezione; apertura senza param → prima lista e URL si aggiorna |
| `frontend/src/pages/SettingsPage.jsx` | Sezione "Share your wishlist" → per-lista (selettore lista + link + "Generate new link"); rimozione del campo "List name" dal form General |
| `frontend/src/pages/AdminPage.jsx` | Rimozione del campo list name dal form di modifica utente |
| `frontend/src/pages/PublicWishlistPage.jsx` | Nessun cambio (forme API preservate) |
| `frontend/src/components/GiftDirectoryList.jsx` | Nessun cambio |
| `frontend/src/pages/ReceivedPage.jsx` | Nessun cambio (fetch globale per utente) |
| `frontend/src/pages/WishlistChooserPage.jsx` | Solo ritocco testi ("My lists") |
| `frontend/src/locales/it.js`, `nl.js` | Nuove stringhe: "Nuova lista", "Rinomina lista", "Elimina lista", conferme, errori |

## 5. Test

- Fixture aggiornati (`Gift` richiede una lista)
- Nuovi test per l'API liste: creazione, rinomina, protezione ultima lista, token per-lista, isolamento tra utenti
- I test di migrazione esistenti copriranno anche la nuova revisione

## 6. Casi limite

- Nuovo utente creato dall'admin → lista di default automatica
- Elimino la lista attiva → passo alla prima lista rimasta
- Nome vuoto → 400
- Liste di altri utenti → 403
- Eliminare una lista elimina anche i suoi regali ricevuti (sparirebbero dalla pagina "Received") → conferma esplicita

## 7. Ordine di lavoro

1. [x] Backend dati (modelli + migrazione)
2. [x] Backend API (liste + items + public + auth/admin)
3. [x] Test backend (TDD: scritti insieme all'API — 82 verdi; la migrazione era già coperta dal punto 1)
4. [x] Frontend (WishlistPage, SettingsPage, AdminPage, i18n) — TDD con vitest + @testing-library (16 test verdi, primo test runner del frontend: `npm test` in `frontend/`)
5. [x] Verifica (22/11/2026): test verdi (backend 82, frontend 16), lint, `check-translations` (dopo fix puntuale pre-esistente su 'Get this gift', v. sotto), `flask db upgrade` sul DB di sviluppo (stampa reale a `d5e6f7a8b9c0` + upgrade → dati migrati: 1 utente, 3 regali riassegnati), prova manuale su localhost:5173 completata (creazione/rinomina/eliminazione liste, protezione ultima lista, URL `?list=<code>`, condivisione per-lista in Impostazioni, link pubblico con claim funzionanti, fallback alla prima lista dopo eliminazione)
   - ⚠️ ~~il DB di sviluppo locale era bloccato alla revisione inesistente `e6f7a8b9c0d1`~~ risolto: la nota originale suggeriva `stamp d6e7f8a9b0c1`, ma quello è l'id della migrazione stessa — lo stamp giusto è **`d5e6f7a8b9c0`** (lo schema era realmente pre-wishlist), poi `flask db upgrade` applica `d6e7f8a9b0c1` per davvero
   - nota ambiente: con AirPlay Receiver attivo, macOS ControlCenter occupa `*:5000` e risponde 403 alle richieste API → per sviluppare: disattivare AirPlay Receiver, o avviare il backend su 5001 e puntare il proxy vite (`frontend/vite.config.js`) a `127.0.0.1:5001`
   - fix extra: `frontend/src/locales/it.js` 'Get this gift' → rimosso il punto finale (rendeva rosso `check-translations` da prima della feature)

## Fuori dal perimetro (estensioni future)

- Spostare un regalo da una lista a un'altra
- Riordino manuale delle liste (drag & drop)
