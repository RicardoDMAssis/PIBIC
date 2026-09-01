"""Referencias TPU e views analiticas.

Revision ID: 20260826_0002
Revises: 20260826_0001
"""
from alembic import op

from bpc_ingestion.models import ReferenciaTpu


revision = "20260826_0002"
down_revision = "20260826_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ReferenciaTpu.__table__.create(bind=op.get_bind(), checkfirst=True)
    op.execute(
        """
        CREATE OR REPLACE VIEW vw_processos_analiticos AS
        SELECT
            r.id AS registro_id,
            p.numero_processo,
            r.tribunal,
            r.grau,
            r.classe_codigo,
            r.classe_nome,
            r.orgao_codigo,
            r.orgao_nome,
            r.data_ajuizamento,
            r.data_ultima_atualizacao,
            EXTRACT(DAY FROM r.data_ultima_atualizacao - r.data_ajuizamento)::bigint
                AS dias_ate_ultima_atualizacao,
            COUNT(DISTINCT m.id) AS quantidade_movimentos,
            MIN(m.data_hora) AS primeiro_movimento,
            MAX(m.data_hora) AS ultimo_movimento,
            COUNT(DISTINCT c.id) AS quantidade_comunicacoes,
            COALESCE(q.status, 'nao_consultado') AS status_comunica
        FROM registros_datajud r
        JOIN processos p ON p.id = r.processo_id
        LEFT JOIN movimentos m ON m.registro_id = r.id
        LEFT JOIN comunicacoes_pje c ON c.processo_id = p.id
        LEFT JOIN consultas_pje q ON q.processo_id = p.id
        GROUP BY r.id, p.numero_processo, q.status
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW vw_cobertura_comunica AS
        WITH universo AS (
            SELECT DISTINCT r.tribunal, r.processo_id
            FROM registros_datajud r
        )
        SELECT
            u.tribunal,
            COUNT(*) AS processos,
            COUNT(q.processo_id) AS consultados,
            COUNT(*) FILTER (WHERE q.status = 'encontrado') AS encontrados,
            COUNT(*) FILTER (WHERE q.status = 'sem_resultado') AS sem_resultado,
            COUNT(*) FILTER (WHERE q.status LIKE 'erro%') AS erros,
            ROUND(100.0 * COUNT(q.processo_id) / NULLIF(COUNT(*), 0), 2) AS cobertura_consulta_pct,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE q.status = 'encontrado')
                / NULLIF(COUNT(q.processo_id), 0), 2
            ) AS taxa_encontro_pct
        FROM universo u
        LEFT JOIN consultas_pje q ON q.processo_id = u.processo_id
        GROUP BY u.tribunal
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS vw_cobertura_comunica")
    op.execute("DROP VIEW IF EXISTS vw_processos_analiticos")
    ReferenciaTpu.__table__.drop(bind=op.get_bind(), checkfirst=True)
