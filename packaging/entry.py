"""Point d'entrée de l'exécutable figé (PyInstaller) : application de bureau et serveur."""

import sys

from finz_local_connector.cli import main

sys.exit(main())
