# Connecteur local de Finz

Le connecteur local lit vos comptes bancaires **sur votre machine ou votre serveur** et envoie
le résultat à [Finz](https://app.finz.alemoreau.fr). Vos identifiants bancaires ne quittent
jamais votre machine : Finz ne reçoit que les comptes, les opérations, les positions et les
ordres.

La lecture des sites des banques est faite par [woob](https://woob.tech) (LGPL), figé à la
version 3.7 avec nos correctifs (`patches/`).

## Installation

### Serveur (Docker, Dokploy)

1. Générez une clé de chiffrement des secrets, et gardez-la (sans elle, les secrets du volume
   sont illisibles) :
   ```bash
   openssl rand -base64 32 | tr '+/' '-_'
   ```
   Image : `ghcr.io/alemoreau/finz-local-connector:latest` (publiée par la CI de ce dépôt).
   Dans Dokploy : une application depuis cette image (ou « Dockerfile » depuis ce dépôt), la
   variable `FINZ_LOCAL_CONNECTOR_KEY` (secret), un volume monté sur `/data`.

   ```bash
   docker run -d --name finz-connecteur --restart unless-stopped \
     -e FINZ_LOCAL_CONNECTOR_KEY=<clé> -v finz-connecteur:/data \
     ghcr.io/alemoreau/finz-local-connector:latest
   ```
2. Démarrez le conteneur : il tourne en service (`run`).
3. Dans Finz, page **Connexions › Connecteur local › Relier un connecteur**, puis :
   ```bash
   docker exec -it <conteneur> finz-local-connector link https://app.finz.alemoreau.fr
   docker exec -it <conteneur> finz-local-connector bank add boursorama
   ```
   `bank add` demande vos identifiants (le mot de passe est masqué) puis lance une première
   synchro, avec la validation de la banque si elle en demande une.

### Poste de travail (ligne de commande)

Python 3.11 ou plus, et [uv](https://docs.astral.sh/uv/) :

```bash
git clone https://github.com/alemoreau/finz-local-connector && cd finz-local-connector
scripts/fetch-modules.sh
uv tool install .
finz-local-connector link https://app.finz.alemoreau.fr
finz-local-connector bank add boursorama
finz-local-connector run
```

Les secrets vont dans le trousseau du système (Trousseau macOS, Gestionnaire d'identification
Windows, Secret Service). Sans trousseau, définissez `FINZ_LOCAL_CONNECTOR_KEY`.

### Application de bureau

Téléchargez l'installeur de votre système dans les
[versions publiées](https://github.com/alemoreau/finz-local-connector/releases/latest) :

| Système | Fichier |
| --- | --- |
| macOS (Apple Silicon) | `.dmg` |
| Windows | `…-setup.exe` |
| Linux | `.AppImage` ou `.deb` |

L'application vit près de l'horloge : fermer la fenêtre la cache, le connecteur continue de
synchroniser. Elle démarre avec l'ordinateur (réglable) et se met à jour seule ; les mises à
jour sont signées par une clé de Finz.

**Premier lancement.** Les installeurs ne sont pas encore signés par Apple ni Microsoft :

- **macOS** : ouvrez l'application une fois, puis Réglages Système › Confidentialité et
  sécurité › « Ouvrir quand même ».
- **Windows** : sur l'avertissement SmartScreen, « Informations complémentaires » › « Exécuter
  quand même ».
- **Linux** : `chmod +x` sur le fichier `.AppImage`, ou installez le `.deb`.

Les Mac Intel ne sont pas encore pris en charge par l'application (la ligne de commande
fonctionne).

## Commandes

| Commande | Rôle |
| --- | --- |
| `link <adresse>` | relier à Finz avec le code affiché par Finz |
| `bank modules [--search x]` | banques prises en charge |
| `bank add <module>` | ajouter une banque, puis première synchro |
| `bank credentials <banque>` | corriger des identifiants refusés |
| `bank list`, `bank remove <banque>` | lister, retirer |
| `sync [--bank <banque>]` | synchroniser maintenant ; les questions de la banque sont posées ici |
| `run` | service : appel à Finz toutes les 5 minutes, synchro toutes les 12 h |
| `status [--local]` | état ; `--local` sans appeler Finz (contrôle de santé) |
| `unlink` | oublier Finz et les banques sur cette machine |
| `key` | générer une clé pour `FINZ_LOCAL_CONNECTOR_KEY` |

Une synchro planifiée ne pose jamais de question : si la banque demande une validation, Finz
vous le signale et la banque attend un `sync` lancé par vous.

## Sécurité

- Le connecteur n'ouvre aucun port. Il n'appelle que Finz (HTTPS obligatoire) et votre banque.
- Le jeton Finz n'a qu'un droit : envoyer les données de ce connecteur. Il se révoque depuis Finz.
- Secrets et sessions bancaires sont chiffrés ; les identifiants ne passent jamais par la ligne
  de commande ni par l'environnement d'un autre processus.
- Le journal local (`logs/` dans le dossier de données) ne contient ni montant, ni libellé, ni
  identifiant de compte. Finz ne reçoit que le type d'une erreur, jamais son message.
- Aucun captcha n'est résolu automatiquement.

## Développement

```bash
uv venv && uv pip install -e . pytest
scripts/fetch-modules.sh
.venv/bin/python -m pytest
cd desktop && npm ci && npm test     # interface de l'application de bureau
```

Une étiquette `vX.Y.Z` publie les installeurs (`.github/workflows/release.yml`) ; la version est
celle de `pyproject.toml`, `desktop/package.json` et `desktop/src-tauri/tauri.conf.json`.

Les tests utilisent une banque factice (`tests/modules/fakebank`) et un faux Finz.

## Licence

LGPL-3.0-or-later, comme woob. Sources de woob : <https://gitlab.com/woob/woob> (version 3.7) ;
nos correctifs sont dans `patches/`.
