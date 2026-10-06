"""Reservas e diagnósticos operacionais da triagem IpeaIA.

Revision ID: 20261006_0006
Revises: 20260922_0005
"""
from alembic import op

from bpc_ingestion.models import TentativaIa


revision = "20261006_0006"
down_revision = "20260922_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    TentativaIa.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    TentativaIa.__table__.drop(bind=op.get_bind(), checkfirst=True)
