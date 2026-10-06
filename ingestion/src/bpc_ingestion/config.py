from __future__ import annotations

import os
from dotenv import load_dotenv
from dataclasses import dataclass


TRIBUNAIS_FEDERAIS = ("TRF1", "TRF2", "TRF3", "TRF4", "TRF5", "TRF6")
TRIBUNAIS_SUPERIORES = ("STJ",)
TRIBUNAIS_ESTADUAIS = (
    "TJAC", "TJAL", "TJAM", "TJAP", "TJBA", "TJCE", "TJDF", "TJES", "TJGO",
    "TJMA", "TJMG", "TJMS", "TJMT", "TJPA", "TJPB", "TJPE", "TJPI", "TJPR",
    "TJRJ", "TJRN", "TJRO", "TJRR", "TJRS", "TJSC", "TJSE", "TJSP", "TJTO",
)
TRIBUNAIS_PADRAO = TRIBUNAIS_FEDERAIS
TRIBUNAIS_DATAJUD = TRIBUNAIS_FEDERAIS + TRIBUNAIS_SUPERIORES + TRIBUNAIS_ESTADUAIS
ASSUNTOS_BPC = (6114, 11946, 11947)


@dataclass(frozen=True)
class Settings:
    datajud_api_key: str | None = None
    transparencia_api_token: str | None = None
    database_url: str = "postgresql+psycopg://bpc:bpc@localhost:5432/bpc"
    raw_data_dir: str = "data/raw"
    datajud_base_url: str = "https://api-publica.datajud.cnj.jus.br"
    comunica_base_url: str = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
    checkpoint_file: str = ".state/datajud-checkpoints.json"
    inss_catalog_api_url: str = "https://dadosabertos.inss.gov.br/api/3/action"
    transparencia_base_url: str = "https://api.portaldatransparencia.gov.br/api-de-dados"
    ipeaia_base_url: str = "https://ipeagpt.ipea.gov.br/api/v1"
    ipeaia_api_token: str | None = None
    ipeaia_model: str = "glm-5.1"
    ipeaia_timeout_seconds: float = 600

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(override=False)
        return cls(
            datajud_api_key=os.getenv("DATAJUD_API_KEY"),
            transparencia_api_token=os.getenv("PORTAL_TRANSPARENCIA_API_TOKEN"),
            database_url=os.getenv(
                "DATABASE_URL", "postgresql+psycopg://bpc:bpc@localhost:5432/bpc"
            ),
            raw_data_dir=os.getenv("RAW_DATA_DIR", "data/raw"),
            datajud_base_url=os.getenv(
                "DATAJUD_BASE_URL", "https://api-publica.datajud.cnj.jus.br"
            ).rstrip("/"),
            comunica_base_url=os.getenv(
                "COMUNICA_BASE_URL",
                "https://comunicaapi.pje.jus.br/api/v1/comunicacao",
            ).rstrip("/"),
            checkpoint_file=os.getenv(
                "DATAJUD_CHECKPOINT_FILE", ".state/datajud-checkpoints.json"
            ),
            inss_catalog_api_url=os.getenv(
                "INSS_CATALOG_API_URL", "https://dadosabertos.inss.gov.br/api/3/action"
            ).rstrip("/"),
            transparencia_base_url=os.getenv(
                "PORTAL_TRANSPARENCIA_BASE_URL",
                "https://api.portaldatransparencia.gov.br/api-de-dados",
            ).rstrip("/"),
            ipeaia_base_url=os.getenv(
                "IPEAIA_BASE_URL", "https://ipeagpt.ipea.gov.br/api/v1"
            ).rstrip("/"),
            ipeaia_api_token=os.getenv("IPEAIA_API_TOKEN"),
            ipeaia_model=os.getenv("IPEAIA_MODEL", "glm-5.1"),
            ipeaia_timeout_seconds=float(os.getenv("IPEAIA_TIMEOUT_SECONDS", "600")),
        )

    def require_datajud_key(self) -> str:
        if not self.datajud_api_key:
            raise ValueError("DATAJUD_API_KEY e obrigatoria para a coleta DataJud")
        return self.datajud_api_key

    def require_transparencia_token(self) -> str:
        if not self.transparencia_api_token:
            raise ValueError("PORTAL_TRANSPARENCIA_API_TOKEN é obrigatório para esta coleta")
        return self.transparencia_api_token

    def require_ipeaia_token(self) -> str:
        if not self.ipeaia_api_token:
            raise ValueError("IPEAIA_API_TOKEN é obrigatório para chamar a IpeaIA")
        return self.ipeaia_api_token
