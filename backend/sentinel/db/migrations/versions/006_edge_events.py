"""Durable edge inbox/outbox. ACK only after commit."""
from alembic import op
import sqlalchemy as sa
revision = '006_edge_events'
down_revision = '005'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('edge_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False),
        sa.Column('agent_id', sa.String(36), nullable=False),
        sa.Column('source_id', sa.String(128), nullable=False),
        sa.Column('event_json', sa.Text(), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_edge_events_tenant_id','edge_events',['tenant_id'])
    op.create_index('ix_edge_events_pending','edge_events',['published_at','received_at'])

def downgrade():
    op.drop_table('edge_events')
