"""Tarefas persistentes do painel operacional.

Revision ID: 20260826_0003
Revises: 20260826_0002
"""
from alembic import op

from bpc_ingestion.models import TarefaPainel


revision = "20260826_0003"
down_revision = "20260826_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    TarefaPainel.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    TarefaPainel.__table__.drop(bind=op.get_bind(), checkfirst=True)
