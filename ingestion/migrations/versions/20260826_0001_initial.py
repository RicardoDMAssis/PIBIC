"""Esquema unificado DataJud, Comunica PJe e IA.

Revision ID: 20260826_0001
Revises:
"""
from alembic import op

from bpc_ingestion.models import Base


revision = "20260826_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=bind)
    op.execute(
        """
        CREATE OR REPLACE VIEW vw_resumo_tribunais AS
        SELECT
            r.tribunal,
            COUNT(DISTINCT r.processo_id) AS processos,
            COUNT(DISTINCT r.id) AS registros_datajud,
            COUNT(DISTINCT m.id) AS movimentos,
            COUNT(DISTINCT c.id) AS comunicacoes_pje
        FROM registros_datajud r
        LEFT JOIN movimentos m ON m.registro_id = r.id
        LEFT JOIN comunicacoes_pje c ON c.processo_id = r.processo_id
        GROUP BY r.tribunal
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute("DROP VIEW IF EXISTS vw_resumo_tribunais")
    Base.metadata.drop_all(bind=bind)
