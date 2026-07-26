"""conftest.py — configuracao global do pytest.

Garante que o diretorio app/ esta no sys.path para que
`from app import app` funcione ao rodar pytest da raiz do repo.
Tambem cria o diretorio app/static temporariamente se nao existir,
evitando RuntimeError do StaticFiles durante a coleta dos testes.
"""
import os
import sys
import shutil
import pytest

# Raiz do repositorio
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT, "app")
STATIC_DIR = os.path.join(APP_DIR, "static")

# Adiciona app/ ao path para que `from app import app` resolva corretamente
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


@pytest.fixture(scope="session", autouse=True)
def ensure_static_dir():
    """Cria app/static vazio se nao existir (necessario para StaticFiles)."""
    created = False
    if not os.path.isdir(STATIC_DIR):
        os.makedirs(STATIC_DIR)
        # Cria um index.html minimo para FileResponse nao falhar
        with open(os.path.join(STATIC_DIR, "index.html"), "w") as f:
            f.write("<html><body>Cockpit Docker</body></html>")
        created = True
    yield
    if created:
        shutil.rmtree(STATIC_DIR)
