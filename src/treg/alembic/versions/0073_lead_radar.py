"""lead radar: a team's ICP, campaigns, runs, leads, evidence, suppression, spend and cache

Revision ID: 0073
Revises: 0072
Create Date: 2026-10-14

Additive only: new tables, each scoped by org_id. `leadrun (campaign_id, slot)` is unique so a
scheduled day can start once even across restarts; `leadsettings` is one row per team and doubles
as the budget lock (application/leads/budget.py).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa



revision: str = '0073'
down_revision: str | Sequence[str] | None = '0072'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('leadcache',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(), nullable=False),
    sa.Column('provider', sa.String(), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['org.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'key', name='uq_leadcache_org_key')
    )
    op.create_index(op.f('ix_leadcache_org_id'), 'leadcache', ['org_id'], unique=False)
    op.create_table('leadicp',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('product', sa.String(), nullable=False),
    sa.Column('website', sa.String(), nullable=False),
    sa.Column('sectors', sa.JSON(), nullable=False),
    sa.Column('geographies', sa.JSON(), nullable=False),
    sa.Column('sizes', sa.JSON(), nullable=False),
    sa.Column('roles', sa.JSON(), nullable=False),
    sa.Column('problems', sa.JSON(), nullable=False),
    sa.Column('competitors', sa.JSON(), nullable=False),
    sa.Column('exclusions', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['org.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_leadicp_org_id'), 'leadicp', ['org_id'], unique=False)
    op.create_table('leadsettings',
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('run_limit_micro', sa.Integer(), nullable=False),
    sa.Column('day_limit_micro', sa.Integer(), nullable=False),
    sa.Column('month_limit_micro', sa.Integer(), nullable=False),
    sa.Column('retention_days', sa.Integer(), nullable=False),
    sa.Column('cache_ttl_hours', sa.JSON(), nullable=False),
    sa.Column('prices_micro', sa.JSON(), nullable=False),
    sa.Column('lock_version', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['org.id'], ),
    sa.PrimaryKeyConstraint('org_id')
    )
    op.create_table('leadsuppression',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('value', sa.String(), nullable=False),
    sa.Column('reason', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['org.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'kind', 'value', name='uq_leadsuppression_value')
    )
    op.create_index(op.f('ix_leadsuppression_org_id'), 'leadsuppression', ['org_id'], unique=False)
    op.create_table('leadcampaign',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('icp_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('provider', sa.String(), nullable=False),
    sa.Column('enrich_provider', sa.String(), nullable=False),
    sa.Column('signal_type', sa.String(), nullable=False),
    sa.Column('queries', sa.JSON(), nullable=False),
    sa.Column('date_range_days', sa.Integer(), nullable=False),
    sa.Column('result_limit', sa.Integer(), nullable=False),
    sa.Column('enrich_limit', sa.Integer(), nullable=False),
    sa.Column('budget_run_micro', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('schedule_daily', sa.Boolean(), nullable=False),
    sa.Column('schedule_hour', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['icp_id'], ['leadicp.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['org.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_leadcampaign_org_id'), 'leadcampaign', ['org_id'], unique=False)
    op.create_table('lead',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Integer(), nullable=True),
    sa.Column('dedup_key', sa.String(), nullable=False),
    sa.Column('company', sa.String(), nullable=False),
    sa.Column('domain', sa.String(), nullable=False),
    sa.Column('person_name', sa.String(), nullable=False),
    sa.Column('person_role', sa.String(), nullable=False),
    sa.Column('person_url', sa.String(), nullable=False),
    sa.Column('location', sa.String(), nullable=False),
    sa.Column('signal_type', sa.String(), nullable=False),
    sa.Column('signal_date', sa.String(), nullable=False),
    sa.Column('summary', sa.String(), nullable=False),
    sa.Column('fit_reason', sa.String(), nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('score_fit', sa.Integer(), nullable=False),
    sa.Column('score_signal', sa.Integer(), nullable=False),
    sa.Column('score_recency', sa.Integer(), nullable=False),
    sa.Column('score_notes', sa.JSON(), nullable=False),
    sa.Column('qualified', sa.Boolean(), nullable=False),
    sa.Column('email', sa.String(), nullable=False),
    sa.Column('email_status', sa.String(), nullable=False),
    sa.Column('provider', sa.String(), nullable=False),
    sa.Column('demo', sa.Boolean(), nullable=False),
    sa.Column('last_enriched_at', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('note', sa.String(), nullable=False),
    sa.Column('discovered_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['campaign_id'], ['leadcampaign.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['org.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'dedup_key', name='uq_lead_org_dedup')
    )
    op.create_index(op.f('ix_lead_org_id'), 'lead', ['org_id'], unique=False)
    op.create_table('leadrun',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Integer(), nullable=False),
    sa.Column('trigger', sa.String(), nullable=False),
    sa.Column('slot', sa.String(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('stop_requested', sa.Boolean(), nullable=False),
    sa.Column('provider', sa.String(), nullable=False),
    sa.Column('demo', sa.Boolean(), nullable=False),
    sa.Column('candidates', sa.Integer(), nullable=False),
    sa.Column('qualified', sa.Integer(), nullable=False),
    sa.Column('new_leads', sa.Integer(), nullable=False),
    sa.Column('enriched', sa.Integer(), nullable=False),
    sa.Column('api_cost_micro', sa.Integer(), nullable=False),
    sa.Column('llm_cost_micro', sa.Integer(), nullable=False),
    sa.Column('issues', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['campaign_id'], ['leadcampaign.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['org.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('campaign_id', 'slot', name='uq_leadrun_campaign_slot')
    )
    op.create_index(op.f('ix_leadrun_campaign_id'), 'leadrun', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_leadrun_org_id'), 'leadrun', ['org_id'], unique=False)
    op.create_table('leadevidence',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('lead_id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=True),
    sa.Column('url', sa.String(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('snippet', sa.String(), nullable=False),
    sa.Column('signal_date', sa.String(), nullable=False),
    sa.Column('provider', sa.String(), nullable=False),
    sa.Column('found_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['lead_id'], ['lead.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['org.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['leadrun.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lead_id', 'url', name='uq_leadevidence_lead_url')
    )
    op.create_index(op.f('ix_leadevidence_lead_id'), 'leadevidence', ['lead_id'], unique=False)
    op.create_index(op.f('ix_leadevidence_org_id'), 'leadevidence', ['org_id'], unique=False)
    op.create_table('leadspend',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=True),
    sa.Column('provider', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('state', sa.String(), nullable=False),
    sa.Column('reserved_micro', sa.Integer(), nullable=False),
    sa.Column('actual_micro', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('settled_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['org_id'], ['org.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['leadrun.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_leadspend_created_at'), 'leadspend', ['created_at'], unique=False)
    op.create_index(op.f('ix_leadspend_org_id'), 'leadspend', ['org_id'], unique=False)
    op.create_index(op.f('ix_leadspend_run_id'), 'leadspend', ['run_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_leadspend_run_id'), table_name='leadspend')
    op.drop_index(op.f('ix_leadspend_org_id'), table_name='leadspend')
    op.drop_index(op.f('ix_leadspend_created_at'), table_name='leadspend')
    op.drop_table('leadspend')
    op.drop_index(op.f('ix_leadevidence_org_id'), table_name='leadevidence')
    op.drop_index(op.f('ix_leadevidence_lead_id'), table_name='leadevidence')
    op.drop_table('leadevidence')
    op.drop_index(op.f('ix_leadrun_org_id'), table_name='leadrun')
    op.drop_index(op.f('ix_leadrun_campaign_id'), table_name='leadrun')
    op.drop_table('leadrun')
    op.drop_index(op.f('ix_lead_org_id'), table_name='lead')
    op.drop_table('lead')
    op.drop_index(op.f('ix_leadcampaign_org_id'), table_name='leadcampaign')
    op.drop_table('leadcampaign')
    op.drop_index(op.f('ix_leadsuppression_org_id'), table_name='leadsuppression')
    op.drop_table('leadsuppression')
    op.drop_table('leadsettings')
    op.drop_index(op.f('ix_leadicp_org_id'), table_name='leadicp')
    op.drop_table('leadicp')
    op.drop_index(op.f('ix_leadcache_org_id'), table_name='leadcache')
    op.drop_table('leadcache')
