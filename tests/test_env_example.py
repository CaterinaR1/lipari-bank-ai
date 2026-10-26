from pathlib import Path

from config import Settings


def test_env_example_matches_settings() -> None:
    example_path = Path(__file__).resolve().parents[1] / ".env.example"
    documented: set[str] = set()

    for line in example_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            documented.add(line.split("=", maxsplit=1)[0])

    expected: set[str] = set()
    prefix = Settings.model_config.get("env_prefix", "")

    for name, field in Settings.model_fields.items():
        if field.exclude:
            continue

        alias = field.validation_alias or field.alias or name

        if isinstance(alias, str):
            expected.add(f"{prefix}{alias}")
        elif alias is None:
            expected.add(f"{prefix}{name}")

    expected = {name.upper() for name in expected}

    assert documented == expected, (
        f"Variabili mancanti nel file di esempio: "
        f"{sorted(expected - documented)}; "
        f"variabili non utilizzate: {sorted(documented - expected)}"
    )
