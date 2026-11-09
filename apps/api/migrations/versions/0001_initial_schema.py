"""Create the initial provenance and research schema.

Revision ID: 0001_initial_schema
Revises:
"""

from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE strategy_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            version TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL,
            configuration JSONB NOT NULL,
            configuration_sha256 CHAR(64) NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT strategy_versions_sha256_check
                CHECK (configuration_sha256 ~ '^[0-9a-f]{64}$')
        );

        CREATE TABLE model_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            provider TEXT NOT NULL,
            model_name TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            configuration JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT model_versions_identity_unique
                UNIQUE (provider, model_name, prompt_version)
        );

        CREATE TABLE assets (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            asset_key TEXT NOT NULL UNIQUE,
            symbol TEXT NOT NULL,
            name TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            external_id TEXT UNIQUE,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT assets_type_check
                CHECK (asset_type IN ('crypto', 'stablecoin', 'wrapped', 'other'))
        );

        CREATE TABLE venues (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            venue_key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            website_url TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE asset_universe_snapshots (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            snapshot_at TIMESTAMPTZ NOT NULL,
            effective_from TIMESTAMPTZ NOT NULL,
            effective_to TIMESTAMPTZ,
            source TEXT NOT NULL,
            source_timestamp TIMESTAMPTZ NOT NULL,
            retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT universe_snapshot_effective_check
                CHECK (effective_to IS NULL OR effective_to > effective_from)
        );

        CREATE TABLE market_pairs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            venue_id UUID NOT NULL REFERENCES venues(id) ON DELETE RESTRICT,
            base_asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
            quote_asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
            venue_symbol TEXT NOT NULL,
            price_increment NUMERIC(38, 18),
            quantity_increment NUMERIC(38, 18),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            first_listed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT market_pairs_venue_symbol_unique UNIQUE (venue_id, venue_symbol),
            CONSTRAINT market_pairs_identity_unique UNIQUE (id, venue_id),
            CONSTRAINT market_pairs_distinct_assets_check CHECK (base_asset_id <> quote_asset_id),
            CONSTRAINT market_pairs_increments_check CHECK (
                (price_increment IS NULL OR price_increment > 0)
                AND (quantity_increment IS NULL OR quantity_increment > 0)
            )
        );

        CREATE TABLE asset_universe_members (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            snapshot_id UUID NOT NULL
                REFERENCES asset_universe_snapshots(id) ON DELETE RESTRICT,
            asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
            rank INTEGER NOT NULL,
            market_cap NUMERIC(38, 18),
            quote_volume_24h NUMERIC(38, 18),
            eligibility JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT universe_members_rank_check CHECK (rank > 0),
            CONSTRAINT universe_members_snapshot_rank_unique UNIQUE (snapshot_id, rank),
            CONSTRAINT universe_members_snapshot_asset_unique UNIQUE (snapshot_id, asset_id)
        );

        CREATE TABLE candles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            venue_id UUID NOT NULL REFERENCES venues(id) ON DELETE RESTRICT,
            market_pair_id UUID NOT NULL,
            interval TEXT NOT NULL,
            open_time TIMESTAMPTZ NOT NULL,
            close_time TIMESTAMPTZ NOT NULL,
            open NUMERIC(38, 18) NOT NULL,
            high NUMERIC(38, 18) NOT NULL,
            low NUMERIC(38, 18) NOT NULL,
            close NUMERIC(38, 18) NOT NULL,
            volume NUMERIC(38, 18) NOT NULL,
            quote_volume NUMERIC(38, 18),
            source TEXT NOT NULL,
            source_timestamp TIMESTAMPTZ NOT NULL,
            retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT candles_pair_venue_fk
                FOREIGN KEY (market_pair_id, venue_id)
                REFERENCES market_pairs(id, venue_id) ON DELETE RESTRICT,
            CONSTRAINT candles_unique_key
                UNIQUE (venue_id, market_pair_id, interval, open_time),
            CONSTRAINT candles_time_check CHECK (close_time > open_time),
            CONSTRAINT candles_ohlc_check CHECK (
                open > 0 AND high > 0 AND low > 0 AND close > 0
                AND high >= low
                AND high >= open AND high >= close
                AND low <= open AND low <= close
            ),
            CONSTRAINT candles_volume_check
                CHECK (volume >= 0 AND (quote_volume IS NULL OR quote_volume >= 0))
        );

        CREATE TABLE market_snapshots (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
            venue_id UUID REFERENCES venues(id) ON DELETE RESTRICT,
            market_pair_id UUID,
            price NUMERIC(38, 18),
            market_cap NUMERIC(38, 18),
            volume_24h NUMERIC(38, 18),
            spread_bps NUMERIC(12, 6),
            observed_at TIMESTAMPTZ NOT NULL,
            source TEXT NOT NULL,
            source_timestamp TIMESTAMPTZ NOT NULL,
            retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT market_snapshots_pair_venue_check
                CHECK ((market_pair_id IS NULL) = (venue_id IS NULL)),
            CONSTRAINT market_snapshots_pair_venue_fk
                FOREIGN KEY (market_pair_id, venue_id)
                REFERENCES market_pairs(id, venue_id) ON DELETE RESTRICT,
            CONSTRAINT market_snapshots_values_check CHECK (
                (price IS NULL OR price > 0)
                AND (market_cap IS NULL OR market_cap >= 0)
                AND (volume_24h IS NULL OR volume_24h >= 0)
                AND (spread_bps IS NULL OR spread_bps >= 0)
            )
        );

        CREATE TABLE news_sources (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source_key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_url TEXT NOT NULL,
            reliability_score NUMERIC(5, 4),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT news_sources_type_check CHECK (source_type IN ('rss', 'api', 'website')),
            CONSTRAINT news_sources_reliability_check
                CHECK (reliability_score IS NULL OR reliability_score BETWEEN 0 AND 1)
        );

        CREATE TABLE news_articles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id UUID NOT NULL REFERENCES news_sources(id) ON DELETE RESTRICT,
            external_id TEXT,
            canonical_url TEXT NOT NULL,
            title TEXT NOT NULL,
            publisher TEXT NOT NULL,
            language TEXT,
            permitted_excerpt TEXT,
            published_at TIMESTAMPTZ,
            source_timestamp TIMESTAMPTZ NOT NULL,
            retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            content_sha256 CHAR(64),
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT news_articles_external_id_unique UNIQUE (source_id, external_id),
            CONSTRAINT news_articles_content_hash_check
                CHECK (content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$')
        );

        CREATE TABLE article_asset_links (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            article_id UUID NOT NULL REFERENCES news_articles(id) ON DELETE RESTRICT,
            asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
            relevance_score NUMERIC(5, 4),
            topic TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT article_asset_links_unique UNIQUE (article_id, asset_id),
            CONSTRAINT article_asset_links_relevance_check
                CHECK (relevance_score IS NULL OR relevance_score BETWEEN 0 AND 1)
        );

        CREATE TABLE analysis_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            strategy_version_id UUID NOT NULL
                REFERENCES strategy_versions(id) ON DELETE RESTRICT,
            model_version_id UUID REFERENCES model_versions(id) ON DELETE RESTRICT,
            scheduled_for TIMESTAMPTZ,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            source_timestamp TIMESTAMPTZ,
            retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            diagnostics JSONB NOT NULL DEFAULT '{}'::jsonb,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT analysis_runs_type_check
                CHECK (run_type IN ('scheduled', 'manual', 'backfill', 'evaluation')),
            CONSTRAINT analysis_runs_status_check
                CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
            CONSTRAINT analysis_runs_time_check
                CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at)
        );

        CREATE TABLE feature_snapshots (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
            venue_id UUID REFERENCES venues(id) ON DELETE RESTRICT,
            market_pair_id UUID,
            interval TEXT NOT NULL,
            as_of TIMESTAMPTZ NOT NULL,
            feature_version TEXT NOT NULL,
            feature_values JSONB NOT NULL,
            source_timestamp TIMESTAMPTZ NOT NULL,
            retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT feature_snapshots_pair_venue_check
                CHECK ((market_pair_id IS NULL) = (venue_id IS NULL)),
            CONSTRAINT feature_snapshots_pair_venue_fk
                FOREIGN KEY (market_pair_id, venue_id)
                REFERENCES market_pairs(id, venue_id) ON DELETE RESTRICT
        );

        CREATE TABLE candidate_rankings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE RESTRICT,
            asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
            strategy_version_id UUID NOT NULL
                REFERENCES strategy_versions(id) ON DELETE RESTRICT,
            rank INTEGER NOT NULL,
            total_score NUMERIC(8, 4) NOT NULL,
            component_scores JSONB NOT NULL,
            eligible BOOLEAN NOT NULL,
            rejection_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT candidate_rankings_rank_check CHECK (rank > 0),
            CONSTRAINT candidate_rankings_score_check CHECK (total_score BETWEEN 0 AND 100),
            CONSTRAINT candidate_rankings_run_rank_unique UNIQUE (analysis_run_id, rank),
            CONSTRAINT candidate_rankings_run_asset_unique UNIQUE (analysis_run_id, asset_id)
        );

        CREATE TABLE daily_briefs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            analysis_run_id UUID NOT NULL UNIQUE
                REFERENCES analysis_runs(id) ON DELETE RESTRICT,
            report_date DATE NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1,
            decision TEXT NOT NULL,
            selected_asset_id UUID REFERENCES assets(id) ON DELETE RESTRICT,
            selected_ranking_id UUID REFERENCES candidate_rankings(id) ON DELETE RESTRICT,
            strategy_version_id UUID NOT NULL
                REFERENCES strategy_versions(id) ON DELETE RESTRICT,
            model_version_id UUID REFERENCES model_versions(id) ON DELETE RESTRICT,
            title TEXT NOT NULL,
            narrative TEXT NOT NULL,
            published_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT daily_briefs_revision_check CHECK (revision > 0),
            CONSTRAINT daily_briefs_date_revision_unique UNIQUE (report_date, revision),
            CONSTRAINT daily_briefs_decision_check CHECK (
                (decision = 'coin_of_the_day' AND selected_asset_id IS NOT NULL)
                OR (decision = 'no_trade' AND selected_asset_id IS NULL)
            )
        );

        CREATE TABLE trade_setups (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            brief_id UUID NOT NULL UNIQUE REFERENCES daily_briefs(id) ON DELETE RESTRICT,
            venue_id UUID NOT NULL REFERENCES venues(id) ON DELETE RESTRICT,
            market_pair_id UUID NOT NULL,
            bias TEXT NOT NULL,
            as_of TIMESTAMPTZ NOT NULL,
            entry_low NUMERIC(38, 18),
            entry_high NUMERIC(38, 18),
            stop_price NUMERIC(38, 18),
            targets JSONB NOT NULL DEFAULT '[]'::jsonb,
            risk_reward_estimate NUMERIC(12, 6),
            fees_bps NUMERIC(12, 6) NOT NULL DEFAULT 0,
            slippage_bps NUMERIC(12, 6) NOT NULL DEFAULT 0,
            assumptions JSONB NOT NULL DEFAULT '{}'::jsonb,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT trade_setups_pair_venue_fk
                FOREIGN KEY (market_pair_id, venue_id)
                REFERENCES market_pairs(id, venue_id) ON DELETE RESTRICT,
            CONSTRAINT trade_setups_bias_check
                CHECK (bias IN ('bullish', 'bearish', 'neutral')),
            CONSTRAINT trade_setups_entry_check CHECK (
                (entry_low IS NULL) = (entry_high IS NULL)
                AND (entry_low IS NULL OR (entry_low > 0 AND entry_high >= entry_low))
            ),
            CONSTRAINT trade_setups_stop_check
                CHECK (stop_price IS NULL OR stop_price > 0),
            CONSTRAINT trade_setups_costs_check
                CHECK (fees_bps >= 0 AND slippage_bps >= 0)
        );

        CREATE TABLE scenario_forecasts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            brief_id UUID NOT NULL REFERENCES daily_briefs(id) ON DELETE RESTRICT,
            asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
            horizon TEXT NOT NULL,
            scenario TEXT NOT NULL,
            lower_bound NUMERIC(38, 18),
            upper_bound NUMERIC(38, 18),
            assumptions JSONB NOT NULL DEFAULT '{}'::jsonb,
            drivers JSONB NOT NULL DEFAULT '[]'::jsonb,
            invalidation TEXT,
            source_timestamp TIMESTAMPTZ NOT NULL,
            retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT scenario_forecasts_identity_unique
                UNIQUE (brief_id, horizon, scenario),
            CONSTRAINT scenario_forecasts_horizon_check
                CHECK (horizon IN ('week', 'month', 'year')),
            CONSTRAINT scenario_forecasts_scenario_check
                CHECK (scenario IN ('bull', 'base', 'bear')),
            CONSTRAINT scenario_forecasts_range_check CHECK (
                (lower_bound IS NULL OR lower_bound > 0)
                AND (upper_bound IS NULL OR upper_bound > 0)
                AND (lower_bound IS NULL OR upper_bound IS NULL OR upper_bound >= lower_bound)
            )
        );

        CREATE TABLE brief_input_references (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            brief_id UUID NOT NULL REFERENCES daily_briefs(id) ON DELETE RESTRICT,
            source_type TEXT NOT NULL,
            source_id UUID,
            source_uri TEXT,
            content_sha256 CHAR(64),
            source_timestamp TIMESTAMPTZ NOT NULL,
            retrieved_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT brief_input_references_target_check
                CHECK (source_id IS NOT NULL OR source_uri IS NOT NULL),
            CONSTRAINT brief_input_references_hash_check
                CHECK (content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT brief_input_references_unique
                UNIQUE NULLS NOT DISTINCT (brief_id, source_type, source_id, source_uri)
        );

        CREATE TABLE evaluation_results (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            brief_id UUID NOT NULL REFERENCES daily_briefs(id) ON DELETE RESTRICT,
            asset_id UUID REFERENCES assets(id) ON DELETE RESTRICT,
            horizon TEXT NOT NULL,
            measured_at TIMESTAMPTZ NOT NULL,
            forward_return NUMERIC(18, 8),
            benchmark_return NUMERIC(18, 8),
            max_adverse_excursion NUMERIC(18, 8),
            max_favourable_excursion NUMERIC(18, 8),
            metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT evaluation_results_brief_horizon_unique UNIQUE (brief_id, horizon)
        );

        CREATE INDEX asset_universe_snapshots_time_idx
            ON asset_universe_snapshots (snapshot_at DESC);
        CREATE INDEX candles_pair_interval_time_idx
            ON candles (market_pair_id, interval, open_time DESC);
        CREATE INDEX market_snapshots_asset_time_idx
            ON market_snapshots (asset_id, observed_at DESC);
        CREATE INDEX news_articles_published_at_idx
            ON news_articles (published_at DESC);
        CREATE INDEX article_asset_links_asset_idx
            ON article_asset_links (asset_id, article_id);
        CREATE INDEX analysis_runs_created_at_idx
            ON analysis_runs (created_at DESC);
        CREATE INDEX feature_snapshots_asset_time_idx
            ON feature_snapshots (asset_id, interval, as_of DESC);
        CREATE INDEX candidate_rankings_run_rank_idx
            ON candidate_rankings (analysis_run_id, rank);
        CREATE INDEX daily_briefs_date_idx ON daily_briefs (report_date DESC);
        CREATE INDEX brief_input_references_brief_idx
            ON brief_input_references (brief_id);

        CREATE FUNCTION reject_append_only_mutation() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'Table % is append-only; % is not permitted',
                TG_TABLE_NAME, TG_OP
                USING ERRCODE = '55000';
        END;
        $$;

        CREATE TRIGGER daily_briefs_append_only
            BEFORE UPDATE OR DELETE OR TRUNCATE ON daily_briefs
            FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();
        CREATE TRIGGER brief_input_references_append_only
            BEFORE UPDATE OR DELETE OR TRUNCATE ON brief_input_references
            FOR EACH STATEMENT EXECUTE FUNCTION reject_append_only_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE evaluation_results;
        DROP TABLE brief_input_references;
        DROP TABLE scenario_forecasts;
        DROP TABLE trade_setups;
        DROP TABLE daily_briefs;
        DROP TABLE candidate_rankings;
        DROP TABLE feature_snapshots;
        DROP TABLE analysis_runs;
        DROP TABLE article_asset_links;
        DROP TABLE news_articles;
        DROP TABLE news_sources;
        DROP TABLE market_snapshots;
        DROP TABLE candles;
        DROP TABLE asset_universe_members;
        DROP TABLE market_pairs;
        DROP TABLE asset_universe_snapshots;
        DROP TABLE venues;
        DROP TABLE assets;
        DROP TABLE model_versions;
        DROP TABLE strategy_versions;
        DROP FUNCTION reject_append_only_mutation();
        """
    )
