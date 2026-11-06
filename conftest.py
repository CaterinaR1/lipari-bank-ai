# conftest.py — nella radice: l'ambiente dei test, prima che qualcosa importi src
import os
from collections.abc import Iterator

import pytest
from alembic.config import Config

from alembic import command

# I test parlano con un database vero: quello di test, mai quello di sviluppo.
# Qui non c'è setdefault: un DATABASE_URL rimasto nell'ambiente porterebbe i test a svuotare
# il database su cui lavori.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://lipari:lipari@localhost:5432/lipari_ai_test"
)
os.environ.setdefault("JWT_SECRET", "segreto-dei-test-lungo-almeno-trentadue-caratteri")


@pytest.fixture(scope="session", autouse=True)
def schema() -> Iterator[None]:
    """Lo schema del database di test, dalle migration e da zero: come lo avrà chi clona."""
    cfg = Config("alembic.ini")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(scope="session", autouse=True)
def modelli_finti() -> Iterator[None]:
    """Nessun test chiama un modello vero: costerebbe, e risponderebbe ogni volta in un modo
    diverso. La chat parla con un finto che ripete la domanda, la categorizzazione usa la regola
    a parole chiave. Un test che vuole un modello preciso mette il suo."""
    from src.api.categorize import get_categorize_service
    from src.llm.factory import get_embedder, get_llm_provider
    from src.main import app
    from tests.finti import CategorizzazioneARegole, ModelloEco, embedder_finto

    app.dependency_overrides[get_llm_provider] = ModelloEco
    app.dependency_overrides[get_categorize_service] = CategorizzazioneARegole
    app.dependency_overrides[get_embedder] = embedder_finto
    yield
    app.dependency_overrides.clear()
