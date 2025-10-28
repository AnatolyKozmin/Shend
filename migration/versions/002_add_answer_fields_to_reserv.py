"""add answer fields to reserv

Revision ID: 002
Revises: merge_revision
Create Date: 2025-10-28

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002'
down_revision = None  # Будет установлено после merge
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем поля для хранения ответов
    op.add_column('reserv', sa.Column('last_answer', sa.String(length=16), nullable=True))
    op.add_column('reserv', sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # Удаляем поля
    op.drop_column('reserv', 'answered_at')
    op.drop_column('reserv', 'last_answer')

