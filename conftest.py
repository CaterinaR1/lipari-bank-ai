import os

# Imposta i valori minimi per i test prima di importare src.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test",
)
os.environ.setdefault(
    "JWT_SECRET",
    "segreto-dei-test-lungo-almeno-trentadue-caratteri",
)
