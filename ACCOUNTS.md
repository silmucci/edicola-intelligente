# Account personali e persistenza — Task 11A

**Task 12.2:** aggiunge chat persistenti opt-in con migrazione manuale
[`004_chat_history.sql`](migrations/004_chat_history.sql). Non cambiano i Secrets.
Per contesto, isolamento, limiti e prova con due utenti vedere
[CHAT_HISTORY.md](CHAT_HISTORY.md). Dopo la 004 verificare RLS forzata e ownership
anche su `chat_settings`, `conversations`, `chat_messages`.

**Estensione Task 12:** autorizzazioni AI persistenti per finalità in
`edicola_private.ai_consents`, con nuova migrazione 003, export e cancellazione
per proprietario. [Procedura e controlli](UX_TASK12.md). Le indicazioni sull'audit
001/002 più sotto si estendono a cinque tabelle e quattro policy dopo la 003.

Il codice è pronto per configurazione manuale. **Non sono stati creati account,
credenziali, progetti Google/Supabase, database remoti o deployment.** I test usano
provider e database simulati; la persistenza reale e le policy SQL devono essere
verificate sull'istanza configurata dal gestore prima dell'apertura pubblica.
Questo documento sostituisce le precedenti indicazioni sul profilo demo cloud.

## Architettura

```text
Browser → Streamlit → Google OIDC nativo (solo quando si preme Accedi)
                   → st.user verificato: issuer + subject + controllo audience
                   → SHA-256(issuer, subject): identificativo pseudonimo stabile
                   → CRUD server-side → PostgreSQL Supabase / schema edicola_private
```

La verifica crittografica OIDC, nonce/state e audience è affidata a Streamlit/Authlib.
Il codice controlla anche provider Google, issuer e audience prima di accedere ai
dati. `email`, nome, query parameters e flag in `session_state` non sono identificatori.
L'issuer Google con/senza prefisso HTTPS viene normalizzato alla forma canonica
`https://accounts.google.com`. Non si decodificano token forniti arbitrariamente
dall'utente. Nel database non vengono salvati password utente, email, nome o token.
L'hash identifica stabilmente il proprietario tra dispositivi: è pseudonimo, non anonimo.

Il corpus e Chroma restano locali al server/snapshot già approvato. La sola area
personale usa PostgreSQL:

| Tabella | Contenuti |
| --- | --- |
| `profiles` | interessi, tempo, formato, feedback e identificativo pseudonimo |
| `saved_passages` | ID del passaggio e metadati PDF/pagina/versione; nessuna copia dell'articolo |
| `briefings` | briefing validati completi di fonti, cache key e data di creazione |

Al primo accesso il profilo è vuoto e non importa preferenze demo. Le righe vengono
create soltanto alla prima scrittura. Le letture dei salvati risolvono i riferimenti
contro l'archivio corrente: una versione non più disponibile è segnalata, non sostituita
silenziosamente con un'altra. I briefing già prodotti restano leggibili da PostgreSQL
anche senza SQLite personale o PDF della vecchia edizione; i link ai PDF non più
disponibili sono disabilitati dai controlli sulle fonti esistenti.

Le connessioni sono brevi, senza pool/cache globale di dati personali. Ogni operazione
verifica nuovamente il proprietario, usa parametri SQL e una transazione. Tutte le
query sui dati hanno il proprietario nei parametri, comprese cache, liste, export
e cancellazioni. Un cambio identità o logout svuota storico chat, bozze, consensi,
export e risultati personali della sessione prima di caricare il nuovo utente.
La cache dei briefing ha chiave composta `(owner_id, cache_key)`: un risultato
identico per un altro utente non autorizza la lettura della sua cache.

### Limiti di fiducia e ruolo database

Non usare `postgres`, il proprietario delle tabelle o una chiave `service_role`
nell'app. Il ruolo `edicola_app` ha solo USAGE sullo schema e CRUD sulle tre tabelle;
ha inoltre SELECT sulla sola tabella di versione `schema_migrations` e non ha
DDL/TRUNCATE, superuser, BYPASSRLS o appartenenza ad altri ruoli. A ogni
transazione il codice rifiuta ruoli amministrativi, con membership o proprietari
dello schema/tabelle personali. RLS è abilitata e forzata sulle tre tabelle.

Il server imposta `edicola.owner_id` con `set_config(..., true)` dalla sola identità
verificata, per la transazione corrente. Le policy controllano questo valore, mentre
il CRUD applica anche filtri espliciti. **RLS non autentica Google**: il ruolo server
può impostare il contesto; chi rubasse le credenziali del server potrebbe impersonare
quel contesto. La protezione dipende anche dal server fidato, dai controlli OIDC e
dalla segretezza delle credenziali. Non vengono considerate sicure query con credenziali
amministrative solo perché esistono policy RLS.

## 1. Preparare dipendenze e ambiente

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
```

Sono aggiunti soltanto Authlib per l'OIDC nativo e `psycopg[binary]` per PostgreSQL,
compatibili con l'ambiente Windows verificato. Non serve Supabase Auth né il suo
SDK: Google autentica l'utente, PostgreSQL conserva i dati. La CI Linux esistente
prova le dipendenze al prossimo push effettuato personalmente dal gestore.

## 2. Configurare Google OIDC manualmente

1. Nella Google Cloud Console scegliere/creare personalmente il progetto del
   prototipo. Aprire **Google Auth Platform**. Non occorre attivare fatturazione
   o abilitare servizi Gemini aggiuntivi per questa integrazione.
2. In **Branding** compilare nome applicazione, contatto del gestore e informazioni
   richieste dal proprio caso. Predisporre l'informativa privacy del servizio.
3. In **Audience** scegliere il pubblico appropriato. Durante la sperimentazione
   mantenere **Testing** e aggiungere esplicitamente i due account Google di prova
   in **Test users**. La pubblicazione del client OAuth è un'azione del gestore.
4. In **Clients → Create client** scegliere **Web application**.
5. Registrare come **Authorized redirect URIs** esattamente:

   ```text
   https://NOME-APP.streamlit.app/oauth2callback
   http://localhost:8501/oauth2callback
   ```

   Inserire l'URL reale; aggiungere localhost solo se si vuole provare OIDC sul PC.
   Il protocollo, il dominio e la porta devono coincidere con l'istanza usata.
   Non occorre un client JavaScript nel browser dell'app.
6. Copiare Client ID e Client Secret esclusivamente nei Secrets. Generare
   personalmente un `cookie_secret` casuale lungo, ad esempio eseguendo localmente:

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

   Usare almeno 32 caratteri casuali: valori corti o il segnaposto di esempio
   non abilitano l'area personale. Non eseguire quel comando in log pubblici e non commettere il valore. Non è
   stato generato durante questo task.
7. Usare la sezione nominata `[auth.google]` del template: `st.login("google")`
   sceglie esattamente quel provider. `scope="openid"` richiede soltanto l'identità
   necessaria; non si richiedono contatti, Gmail, Drive o access token esposti.
8. Sul PC creare manualmente `.streamlit/secrets.toml` (già ignorato); nel cloud
   incollare il TOML in **App settings → Secrets**. Riavviare l'app dopo aver
   aggiornato la configurazione.

Le sessioni seguono le garanzie native Streamlit: il cookie d'identità dura fino
a 30 giorni se non si esce. Login e logout creano una nuova sessione. Logout non
chiude automaticamente le altre schede già aperte e Google non viene disconnesso
globalmente dall'account: non vengono promessi logout globale o revoca di tutte le
sessioni. La rotazione di `cookie_secret` invalida i cookie dell'installazione;
usare un valore stabile tra i normali riavvii per mantenerne il comportamento.

## 3. Configurare Supabase e creare lo schema

1. Creare personalmente il progetto Supabase nel piano scelto e annotarne regione
   e limiti. Non sono richiesti servizi obbligatoriamente a pagamento dal codice.
   Non attivare opzioni a pagamento per tentativi di connessione.
2. Nel **SQL Editor**, con il ruolo amministrativo del progetto, eseguire integralmente
   [`migrations/001_personal_accounts.sql`](migrations/001_personal_accounts.sql).
   Il file è la migrazione versionata iniziale: crea schema, ruolo limitato, tabelle,
   chiavi esterne con cancellazione a cascata, RLS e versione. Non crea altri database
   né contiene password. Va eseguito manualmente, mai all'avvio dell'app.
3. Assegnare personalmente una password forte al ruolo **edicola_app**, ad esempio
   tramite una sessione amministrativa `psql` con il comando interattivo:

   ```text
   \password edicola_app
   ```

   In alternativa il gestore può usare il proprio strumento amministrativo per
   impostarla. Non salvare la password in migration, README, SQL condiviso, shell
   history o repository. Non usare nell'app la password di `postgres`.
4. Nel dashboard **Connect → Session pooler** copiare l'host effettivo e la porta
   (normalmente 5432). Non ricostruire l'host dalla regione. Per il ruolo limitato
   lo username del pooler è **`edicola_app.PROJECT_REF`**, non `postgres.PROJECT_REF`.
   Il Session pooler offre IPv4 senza richiedere un add-on IPv4; la connessione
   diretta va bene se la rete supporta l'endpoint, usando username `edicola_app`.
5. Configurare `[personal_database]` con host, porta, dbname `postgres`, username e
   password del solo ruolo applicativo. I valori sono passati separatamente al
   driver: non costruire URL con password interpolate.
6. Il codice impone **`sslmode=verify-full`**; non effettua downgrade TLS. Il valore
   `sslrootcert="system"` usa le CA di sistema della libpq installata. Se la CA del
   proprio progetto non è riconosciuta, scaricare manualmente il **certificato CA
   pubblico** da **Database Settings → SSL Configuration**, salvarlo come
   `deployment/supabase-ca.crt` e impostare quel percorso relativo nei Secrets.
   Il certificato CA pubblico può essere distribuito dopo verifica; non è una
   chiave privata. Abilitare l'enforcement SSL del progetto secondo le indicazioni
   del fornitore. Non disabilitare la verifica per risolvere un errore di connessione.
7. Non aggiungere **edicola_private** agli schemi esposti dalla Data API. Non
   servono anon key, API key Supabase o service-role key nel browser o nei Secrets
   dell'app. Non usare le sessioni Google come se fossero JWT Supabase Auth.

Controlli amministrativi utili dopo la migrazione:

```sql
SELECT rolname, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolinherit
FROM pg_roles WHERE rolname = 'edicola_app';
SELECT schemaname, tablename, tableowner
FROM pg_tables WHERE schemaname = 'edicola_private';
SELECT tablename, policyname, roles, qual, with_check
FROM pg_policies WHERE schemaname = 'edicola_private';
SELECT version FROM edicola_private.schema_migrations;
```

Tutti i privilegi amministrativi del ruolo applicativo devono risultare falsi;
non deve essere proprietario dello schema/tabelle né membro di altri ruoli.
RLS è difesa aggiuntiva: verificare anche i controlli applicativi con due utenti.
La suite simulata non sostituisce un test d'integrazione sul PostgreSQL reale.

### Verifica dopo una migrazione 001 modificata manualmente

La copia locale esaminata durante la verifica pre-pubblicazione aveva rimosso
gli `ALTER ROLE` e i flag espliciti di creazione del ruolo, ma anche il
`GRANT SELECT ON edicola_private.schema_migrations TO edicola_app`.
La seconda modifica è incompatibile con `PostgresPersonalStore`: prima di ogni
CRUD il codice legge la versione 1 con il ruolo applicativo. La presenza delle
tre tabelle e di RLS non basta a rendere funzionanti profili e briefing.
Era inoltre rimasta soltanto la revoca sulla tabella di versione: un ruolo
preesistente poteva conservare privilegi eccedenti sulle altre tabelle.

La 001 corretta mantiene `CREATE ROLE ... LOGIN NOINHERIT`, senza tentare
`ALTER ROLE` che richiedano privilegi non concessi dall'istanza Supabase.
PostgreSQL crea il ruolo senza privilegi amministrativi per default. Invece di
modificare silenziosamente un ruolo esistente, la migrazione si interrompe se
trova privilegi amministrativi, replica, ereditarietà, membership o proprietà
di oggetti dello schema personale. Il codice verifica gli stessi requisiti
prima di accedere ai dati. Non aggirare un errore usando `postgres` nell'app.

**Istanza già configurata:** eseguire manualmente nel SQL Editor
[`002_personal_accounts_permissions.sql`](migrations/002_personal_accounts_permissions.sql).
La riparazione è transazionale e ripetibile: ripristina i soli permessi necessari
e registra la versione 2, senza modificare dati o policy RLS. La versione 1 resta
registrata per compatibilità con il codice esistente. Per un database nuovo
eseguire 001 e poi 002. Nessuno di questi file viene eseguito dall'app.

Prima e dopo la riparazione eseguire
[`audit_personal_accounts.sql`](migrations/audit_personal_accounts.sql) nel SQL
Editor: è in sola lettura e non legge dati personali o credenziali. Esaminare
tutti i risultati (se l'editor mostra soltanto l'ultimo, eseguire i SELECT
singolarmente). Confrontare con la 001:

| Controllo | Risultato richiesto |
| --- | --- |
| Ruolo | Unico `edicola_app`, LOGIN vero; superuser, CREATEDB, CREATEROLE, REPLICATION, BYPASSRLS, INHERIT falsi |
| Membership e proprietà | `no_memberships`, `not_schema_owner`, `not_table_owner` veri |
| Schema | `app_usage` vero, `app_create` falso |
| Tabelle | Quattro tabelle nello schema privato, comprese `schema_migrations` |
| Versioni | 1 e 2 presenti; nessun permesso di scrittura applicativo sulla tabella versioni |
| Tabelle personali | SELECT/INSERT/UPDATE/DELETE veri; TRUNCATE/TRIGGER/REFERENCES falsi; RLS e FORCE RLS veri |
| Policy | Esattamente una per tabella personale, ALL, TO edicola_app, confronto owner_id/GUC sia USING che WITH CHECK |
| Altri grant | Nessun accesso PUBLIC/anon/authenticated e nessun grant option per edicola_app |
| Struttura | Colonne, PK composte, CHECK e FK ON DELETE CASCADE corrispondenti alla 001 |

Policy aggiuntive, colonne o vincoli diversi devono essere verificati dal gestore:
002 ripara i permessi, non presume di conoscere tutte le modifiche remote.
Un risultato mancante o un errore SQL non costituisce un controllo superato.
La copia locale del file non dimostra quale SQL sia stato effettivamente eseguito
su Supabase: servono i risultati dei cataloghi. Nessuna connessione remota è stata
effettuata durante questa verifica e i test automatici usano soltanto simulazioni.

**Secrets:** la configurazione locale verificata ha callback localhost valido,
modalità `accounts`, ruolo applicativo del Session pooler sulla porta 5432 e
verifica TLS completa nel codice. Le credenziali non sono state stampate né usate
per connettersi. Per il cloud copiare manualmente i Secrets nelle impostazioni
dell'app, sostituire il callback con `https://<app>.streamlit.app/oauth2callback`
e autorizzare esattamente quell'URI nel client Google; conservare quello localhost
per lo sviluppo. Verificare separatamente connessione/TLS dalla rete cloud.
Non versionare `.streamlit/secrets.toml` o `.env` (entrambi esclusi da Git).

**Altri controlli prima della prova online:** nella copia esaminata è attivo
`EDICOLA_CLOUD_DEMO=1`, ma l'accesso a `deployment/seed/manifest.json` da questa
sessione restituisce `PermissionError`. Non è quindi possibile confermare qui
la disponibilità dello snapshot, né dichiararlo assente. Verificarlo nell'ambiente
di esecuzione: se assente o non leggibile, `app.py` si ferma prima dell'Archivio.
Lo snapshot deve essere autorizzato secondo DEPLOYMENT.md; non va ricreato
automaticamente e non va disattivata la protezione per avviare reindicizzazioni.
Alcuni file seed risultano tracciati da Git: `.gitignore` non rimuove contenuti
già tracciati. Verificare i diritti di distribuzione anche della cronologia prima
di rendere pubblico il repository. Nessun file o permesso del seed è stato modificato.

La prova finale va eseguita con due account Google e browser/sessioni distinti,
come descritto più sotto: preferenze diverse, stesso riferimento salvato,
logout/login, export e cancellazione del solo account corrente. Per verificare la
persistenza dei briefing senza Gemini, recuperare briefing personali già
esistenti: quelli generali in SQLite non vengono importati. Se non ve ne sono,
questa verifica resta da effettuare in un secondo momento con invio autorizzato.
Gli audio continuano a essere temporanei, non persistiti in PostgreSQL.

Esito della verifica locale: **494 test superati**, di cui **45 sugli account**,
con provider/database simulati; `python -m pip check` senza dipendenze incompatibili.
La suite ora isola anche i Secrets e la modalità cloud della macchina, per non
leggere credenziali reali né cambiare scenario in base alla configurazione locale.
Questi risultati verificano il codice, non certificano i grant dell'istanza remota.
I default dei ruoli PostgreSQL sono documentati in
[CREATE ROLE](https://www.postgresql.org/docs/current/sql-createrole.html).

## 4. Secrets necessari

Usare **`deployment/secrets.example.toml`**, sostituendo manualmente tutti i segnaposto.

- Principali: `EDICOLA_PROFILE_MODE="accounts"`, `EDICOLA_CLOUD_DEMO="1"` per lo
  snapshot cloud, `EDICOLA_ARCHIVE_DIAGNOSTICS="0"`, `EDICOLA_PRIVACY_CONTACT`.
- Gemini: `GEMINI_API_KEY`, `GEMINI_RAG_MODEL`, `GEMINI_RAG_TOP_K`,
  `GEMINI_TTS_MODEL`, `GEMINI_TTS_VOICE`, copiando i modelli già verificati.
- `[auth]`: `redirect_uri`, `cookie_secret`, `expose_tokens=[]`.
- `[auth.google]`: `client_id`, `client_secret`, `server_metadata_url`, `client_kwargs`.
- `[personal_database]`: `host`, `port`, `dbname`, `user`, `password`, `sslrootcert`.

Auth e database leggono soltanto i Secrets server-side. Non incollare questi
valori in campi Streamlit o file versionati. Senza OIDC configurato il login è
disabilitato e l'archivio resta pubblico. Con OIDC valido ma database assente o
non raggiungibile appare un errore, senza importazione demo o conferma di salvataggio.
Le credenziali amministrative servono solo alla configurazione esterna, mai all'app.

## 5. Modalità di sviluppo Windows separata

Il default è **accounts**, anche su Windows. Per esercitare gli account sul PC
configurare OIDC/Secrets e usare il callback localhost. Per usare invece le vecchie
funzioni dimostrative SQLite, esclusivamente nello sviluppo Windows:

```powershell
$env:EDICOLA_PROFILE_MODE="local_demo"
$env:EDICOLA_CLOUD_DEMO="0"
.\.venv\Scripts\python.exe -m streamlit run app.py
```

L'interfaccia indica **Sviluppo locale · profilo demo condiviso**. Questo profilo
non viene convertito o importato in PostgreSQL. La demo locale non è abilitabile
su Linux/Community Cloud, anche se viene lasciato `local_demo` nella configurazione.
Per tornare agli account impostare `EDICOLA_PROFILE_MODE="accounts"`. Per pubblicare
il corpus rimane valida la procedura autorizzata di `DEPLOYMENT.md`; non cambia
ingestion, chunking, embeddings, Chroma o autorizzazione dei PDF.

## 6. Prova manuale con due utenti

1. Configurare Google, migrazione, ruolo limitato e Secrets. Verificare il caricamento
   dell'Archivio da ospite: nessun profilo demo né chiamata Gemini.
2. Aprire una finestra browser normale (**A**) e una in incognito/altro browser
   (**B**). Accedere con i due account Google aggiunti ai Test users.
3. In A scegliere `Scuola`, 2 minuti, testo; salvare. In B scegliere `Ambiente`,
   10 minuti, audio; salvare. Ricaricare entrambe le finestre: le preferenze devono
   restare differenti. Una conferma appare soltanto dopo il commit.
4. Salvare una lettura e dare feedback in A. B non deve vedere quel salvataggio
   né il feedback. Esportare i dati di entrambi e verificare le differenze.
5. Facoltativamente generare un briefing in A dopo consenso esplicito: questa è
   una prova reale che può usare quota Gemini. Non viene eseguita dai test automatici.
   B non deve vedere il briefing di A, neppure con gli stessi interessi.
6. Effettuare logout in A, accedere con B nella stessa finestra e verificare che
   spariscano bozze, consensi, storico chat, export e briefing selezionato di A.
   Tornare ad A e verificare il recupero dei suoi dati dal database.
7. Riavviare l'app da gestore e accedere ad A da un altro dispositivo. Preferenze,
   riferimenti e briefing devono essere recuperati da PostgreSQL. Non è necessario
   che esistano i vecchi SQLite/cache personali locali. Gli audio possono mancare.
8. Cancellare i dati di A con la conferma richiesta: devono sparire profilo,
   riferimenti e briefing di A, mentre B resta invariato. Verificare l'export di B
   e, da amministratore, la rimozione delle righe del proprietario A.
9. In una copia di test, rendere il database non disponibile o usare una password
   errata: devono apparire errori, **mai** conferme di salvataggio o dati demo.
   Ripristinare la configurazione; non usare credenziali amministrative come ripiego.

I test di tentativi di accesso a proprietari diversi sono automatici con provider e
database simulati. Il browser non dispone di un parametro per scegliere `owner_id`;
aggiungere query parameters o modificare interessi non può cambiare il proprietario.

## Persistente, temporaneo e privacy

**Persistenti:** profili, preferenze, feedback, riferimenti e briefing validati
su PostgreSQL; la disponibilità dipende dal progetto Supabase e dai suoi limiti,
backup e ciclo di vita, non dal disco di Community Cloud. Un progetto eliminato
o non disponibile non equivale a un salvataggio locale sostitutivo.

**Temporanei:** storico chat e bozze nella sessione; file audio personali e loro
copie tecniche del briefing sotto `.private-runtime/<proprietario>/`; cache e
audio dei prodotti generali già esistenti. L'adattatore TTS può materializzare una
copia SQLite del solo briefing scelto per usare il motore audio esistente: è una
copia di lavoro riproducibile da PostgreSQL, non lo storage autorevole dei briefing.
Gli audio non vengono rigenerati automaticamente dopo la loro perdita.

Audio ed export personali passano al browser nel WebSocket della sessione: il
lettore/download usa Blob URL del browser, senza creare URL media pubblici nella
cache generale Streamlit. Non si usa `st.cache_data` per profili, export o prodotti
personali. I file audio del proprietario sono separati anche quando testo/modello/
voce coincidono con quelli di un altro utente. La cancellazione rimuove i dati
PostgreSQL e gli audio locali del proprietario; un errore di pulizia viene segnalato
separatamente. Non cancella l'account Google né copie già scaricate dall'utente.

Prima della pubblicazione il gestore deve completare l'informativa: titolare e
contatti, finalità, fornitori/regioni effettivi, conservazione e procedure per
richieste/esportazione/cancellazione, inclusi i tempi di backup dei fornitori.
Il pannello Privacy dell'app fornisce le informazioni tecniche essenziali e il
contatto configurato; non attesta da solo conformità normativa.

## Riferimenti ufficiali

- [Google OIDC con Streamlit](https://docs.streamlit.io/develop/tutorials/authentication/google).
- [Configurazione di st.login](https://docs.streamlit.io/develop/api-reference/user/st.login).
- [Sessioni e logout Streamlit](https://docs.streamlit.io/develop/concepts/connections/authentication).
- [Connessioni e ruoli custom Supabase](https://supabase.com/docs/guides/database/connecting-to-postgres).
- [TLS PostgreSQL Supabase](https://supabase.com/docs/guides/platform/ssl-enforcement).
- [Transazioni Psycopg](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).
