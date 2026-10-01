-- DuckDB model tables for normalized Parquet data.
-- Python replaces __OUTPUT_DIR__ before execution.

CREATE OR REPLACE TABLE token_entities AS
SELECT * FROM read_parquet('__OUTPUT_DIR__/tokens.parquet');

CREATE OR REPLACE TABLE pool_entities AS
SELECT * FROM read_parquet('__OUTPUT_DIR__/pools.parquet');

CREATE OR REPLACE TABLE normalized_events AS
SELECT * FROM read_parquet('__OUTPUT_DIR__/events.parquet');

CREATE OR REPLACE TABLE primary_outcomes AS
SELECT * FROM read_parquet('__OUTPUT_DIR__/outcomes.parquet');

CREATE OR REPLACE TABLE candidate_frame AS
SELECT * FROM read_parquet('__OUTPUT_DIR__/candidates.parquet');

CREATE OR REPLACE TABLE sampling_manifest AS
SELECT * FROM read_parquet('__OUTPUT_DIR__/sampling.parquet');

CREATE OR REPLACE TABLE split_manifest AS
SELECT * FROM read_parquet('__OUTPUT_DIR__/splits.parquet');

CREATE OR REPLACE TABLE point_in_time_features AS
SELECT * FROM read_parquet('__OUTPUT_DIR__/features.parquet');

CREATE OR REPLACE TABLE feature_audit AS
SELECT * FROM read_parquet('__OUTPUT_DIR__/feature_audit.parquet');

CREATE OR REPLACE TABLE request_manifest AS
SELECT * FROM read_parquet('__OUTPUT_DIR__/request_log.parquet');

CREATE OR REPLACE TABLE censoring_manifest AS
SELECT * FROM read_parquet('__OUTPUT_DIR__/censoring.parquet');

CREATE OR REPLACE TABLE supervised_model_table AS
SELECT f.*, o.label, o.followup_volume_usd, o.volume_complete,
       s.partition, s.overlap_group, s.exclusion_reason
FROM point_in_time_features AS f
JOIN primary_outcomes AS o USING (token_address, source_dataset)
JOIN split_manifest AS s USING (token_address, source_dataset)
WHERE o.label IN ('low_volume_dead', 'continued_activity')
  AND o.volume_complete = TRUE
  AND f.feature_complete = TRUE
  AND s.partition IN ('train', 'validation', 'test');

CREATE OR REPLACE TABLE event_key_quality AS
SELECT token_address, transaction_hash, log_index,
       COUNT(*) AS row_count, COUNT(DISTINCT event_id) AS event_id_count
FROM normalized_events
GROUP BY 1, 2, 3;

CREATE OR REPLACE TABLE feature_cutoff_quality AS
SELECT token_address, source_dataset,
       post_cutoff_event_count AS post_cutoff_events_excluded,
       pre_t0_event_count AS pre_t0_events_excluded,
       missing_timestamp_count AS events_with_missing_timestamp
FROM feature_audit;

CREATE OR REPLACE TABLE label_counts AS
SELECT label, COUNT(*) AS token_count,
       SUM(CASE WHEN volume_complete THEN 1 ELSE 0 END) AS volume_complete_count
FROM primary_outcomes
GROUP BY 1;

CREATE OR REPLACE TABLE split_counts AS
SELECT partition, label, COUNT(*) AS token_count,
       SUM(CASE WHEN censoring_status THEN 1 ELSE 0 END) AS censored_count
FROM split_manifest
GROUP BY 1, 2;
