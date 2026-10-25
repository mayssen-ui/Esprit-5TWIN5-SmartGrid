"""Configuration centrale de l'application (lue depuis l'environnement / .env)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Espace de noms de l'ontologie SmartGrid
NS = "http://www.semanticweb.org/smartgrid-semantic#"


def _path(valeur: str) -> Path:
    p = Path(valeur)
    return p if p.is_absolute() else ROOT / p


class Settings:
    """Paramètres lus dynamiquement (utile pour les tests qui modifient l'environnement)."""

    @property
    def backend(self) -> str:
        return os.getenv("SG_BACKEND", "rdflib").lower()

    @property
    def owl_path(self) -> Path:
        return _path(os.getenv("SG_OWL_PATH", "data/SmartGrid-Semantic.owl"))

    @property
    def data_dir(self) -> Path:
        d = _path(os.getenv("SG_DATA_DIR", "data"))
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def logs_dir(self) -> Path:
        d = self.data_dir / "logs"
        d.mkdir(exist_ok=True)
        return d

    @property
    def fuseki_url(self) -> str:
        return os.getenv("FUSEKI_URL", "http://localhost:3030").rstrip("/")

    @property
    def fuseki_dataset(self) -> str:
        return os.getenv("FUSEKI_DATASET", "smartgrid")

    @property
    def anthropic_key(self) -> str:
        return os.getenv("ANTHROPIC_API_KEY", "").strip()

    @property
    def anthropic_model(self) -> str:
        return os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")

    @property
    def max_results(self) -> int:
        return int(os.getenv("SG_MAX_RESULTS", "500"))

    @property
    def admin_password(self) -> str:
        return os.getenv("SG_ADMIN_PASSWORD", "admin123")

    @property
    def reader_password(self) -> str:
        return os.getenv("SG_READER_PASSWORD", "lecteur123")

    @property
    def api_auth(self) -> bool:
        return os.getenv("SG_API_AUTH", "true").lower() in ("1", "true", "oui", "yes")

    @property
    def secret_key(self) -> str:
        return os.getenv("SG_SECRET_KEY", "changez-moi")


settings = Settings()
