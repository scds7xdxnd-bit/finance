-- SQLite schema capability verification for vNext.
-- Contract: one deterministic row per canonical global artifact_id.
-- Usage:
--   sqlite3 /path/to/db.sqlite < scripts/verify_schema_capabilities.sql

WITH required(scope, artifact_type, artifact_id, table_name, artifact_name) AS (
    SELECT 'global', 'check', 'check:csv_import_batch.ck_csv_import_batch_status', 'csv_import_batch', 'ck_csv_import_batch_status'
    UNION ALL SELECT 'global', 'check', 'check:csv_import_row.ck_csv_import_row_direction', 'csv_import_row', 'ck_csv_import_row_direction'
    UNION ALL SELECT 'global', 'check', 'check:journal_line.ck_journal_line_dc', 'journal_line', 'ck_journal_line_dc'
    UNION ALL SELECT 'global', 'check', 'check:tb_reset_snapshot.ck_tb_reset_snapshot_file_size_nonneg', 'tb_reset_snapshot', 'ck_tb_reset_snapshot_file_size_nonneg'
    UNION ALL SELECT 'global', 'check', 'check:tb_reset_snapshot.ck_tb_reset_snapshot_restore_status', 'tb_reset_snapshot', 'ck_tb_reset_snapshot_restore_status'
    UNION ALL SELECT 'global', 'check', 'check:tb_reset_snapshot.ck_tb_reset_snapshot_sha256_len', 'tb_reset_snapshot', 'ck_tb_reset_snapshot_sha256_len'
    UNION ALL SELECT 'global', 'check', 'check:transaction_journal_link.ck_tx_journal_link_source_nonempty', 'transaction_journal_link', 'ck_tx_journal_link_source_nonempty'
    UNION ALL SELECT 'global', 'check', 'check:transaction_link_candidate.ck_tx_link_candidate_source_nonempty', 'transaction_link_candidate', 'ck_tx_link_candidate_source_nonempty'
    UNION ALL SELECT 'global', 'column', 'column:admin_action_audit.action', 'admin_action_audit', 'action'
    UNION ALL SELECT 'global', 'column', 'column:admin_action_audit.actor_user_id', 'admin_action_audit', 'actor_user_id'
    UNION ALL SELECT 'global', 'column', 'column:admin_action_audit.created_at', 'admin_action_audit', 'created_at'
    UNION ALL SELECT 'global', 'column', 'column:admin_action_audit.status', 'admin_action_audit', 'status'
    UNION ALL SELECT 'global', 'column', 'column:journal_entry.posted_at', 'journal_entry', 'posted_at'
    UNION ALL SELECT 'global', 'column', 'column:tb_reset_snapshot.db_copy_path', 'tb_reset_snapshot', 'db_copy_path'
    UNION ALL SELECT 'global', 'column', 'column:tb_reset_snapshot.file_size_bytes', 'tb_reset_snapshot', 'file_size_bytes'
    UNION ALL SELECT 'global', 'column', 'column:tb_reset_snapshot.restore_status', 'tb_reset_snapshot', 'restore_status'
    UNION ALL SELECT 'global', 'column', 'column:tb_reset_snapshot.sha256', 'tb_reset_snapshot', 'sha256'
    UNION ALL SELECT 'global', 'column', 'column:transaction_journal_link.journal_entry_id', 'transaction_journal_link', 'journal_entry_id'
    UNION ALL SELECT 'global', 'column', 'column:transaction_journal_link.source', 'transaction_journal_link', 'source'
    UNION ALL SELECT 'global', 'column', 'column:transaction_journal_link.transaction_id', 'transaction_journal_link', 'transaction_id'
    UNION ALL SELECT 'global', 'column', 'column:transaction_link_candidate.confidence', 'transaction_link_candidate', 'confidence'
    UNION ALL SELECT 'global', 'column', 'column:transaction_link_candidate.journal_entry_id', 'transaction_link_candidate', 'journal_entry_id'
    UNION ALL SELECT 'global', 'column', 'column:transaction_link_candidate.source', 'transaction_link_candidate', 'source'
    UNION ALL SELECT 'global', 'column', 'column:transaction_link_candidate.status', 'transaction_link_candidate', 'status'
    UNION ALL SELECT 'global', 'column', 'column:transaction_link_candidate.transaction_id', 'transaction_link_candidate', 'transaction_id'
    UNION ALL SELECT 'global', 'index', 'index:admin_action_audit.ix_admin_action_audit_actor_created', 'admin_action_audit', 'ix_admin_action_audit_actor_created'
    UNION ALL SELECT 'global', 'index', 'index:csv_import_row.ix_csv_import_row_user_status', 'csv_import_row', 'ix_csv_import_row_user_status'
    UNION ALL SELECT 'global', 'index', 'index:journal_entry.ix_journal_entry_user_date_parsed', 'journal_entry', 'ix_journal_entry_user_date_parsed'
    UNION ALL SELECT 'global', 'index', 'index:journal_entry.ix_journal_entry_user_reference', 'journal_entry', 'ix_journal_entry_user_reference'
    UNION ALL SELECT 'global', 'index', 'index:journal_line.ix_journal_line_account_dc_journal', 'journal_line', 'ix_journal_line_account_dc_journal'
    UNION ALL SELECT 'global', 'index', 'index:journal_line.ix_journal_line_journal_account_dc', 'journal_line', 'ix_journal_line_journal_account_dc'
    UNION ALL SELECT 'global', 'index', 'index:tb_reset_snapshot.ix_tb_reset_snapshot_user_created', 'tb_reset_snapshot', 'ix_tb_reset_snapshot_user_created'
    UNION ALL SELECT 'global', 'index', 'index:transaction_journal_link.ix_tx_journal_link_user_journal', 'transaction_journal_link', 'ix_tx_journal_link_user_journal'
    UNION ALL SELECT 'global', 'index', 'index:transaction_journal_link.ix_tx_journal_link_user_source', 'transaction_journal_link', 'ix_tx_journal_link_user_source'
    UNION ALL SELECT 'global', 'index', 'index:transaction_link_candidate.ix_tx_link_candidate_user_status', 'transaction_link_candidate', 'ix_tx_link_candidate_user_status'
    UNION ALL SELECT 'global', 'index', 'index:transaction_link_candidate.ix_tx_link_candidate_user_tx_reason', 'transaction_link_candidate', 'ix_tx_link_candidate_user_tx_reason'
    UNION ALL SELECT 'global', 'table', 'table:admin_action_audit', 'admin_action_audit', NULL
    UNION ALL SELECT 'global', 'table', 'table:csv_import_batch', 'csv_import_batch', NULL
    UNION ALL SELECT 'global', 'table', 'table:csv_import_row', 'csv_import_row', NULL
    UNION ALL SELECT 'global', 'table', 'table:journal_entry', 'journal_entry', NULL
    UNION ALL SELECT 'global', 'table', 'table:journal_entry_balance', 'journal_entry_balance', NULL
    UNION ALL SELECT 'global', 'table', 'table:journal_line', 'journal_line', NULL
    UNION ALL SELECT 'global', 'table', 'table:tb_reset_snapshot', 'tb_reset_snapshot', NULL
    UNION ALL SELECT 'global', 'table', 'table:transaction_journal_link', 'transaction_journal_link', NULL
    UNION ALL SELECT 'global', 'table', 'table:transaction_link_candidate', 'transaction_link_candidate', NULL
    UNION ALL SELECT 'global', 'trigger', 'trigger:trg_journal_entry_bi_post_balance_guard', 'journal_entry', 'trg_journal_entry_bi_post_balance_guard'
    UNION ALL SELECT 'global', 'trigger', 'trigger:trg_journal_entry_bu_post_balance_guard', 'journal_entry', 'trg_journal_entry_bu_post_balance_guard'
    UNION ALL SELECT 'global', 'trigger', 'trigger:trg_journal_line_ad_balance', 'journal_line', 'trg_journal_line_ad_balance'
    UNION ALL SELECT 'global', 'trigger', 'trigger:trg_journal_line_ai_balance', 'journal_line', 'trg_journal_line_ai_balance'
    UNION ALL SELECT 'global', 'trigger', 'trigger:trg_journal_line_au_balance', 'journal_line', 'trg_journal_line_au_balance'
    UNION ALL SELECT 'global', 'unique', 'unique:csv_import_batch.uq_csv_import_batch_user_file', 'csv_import_batch', 'uq_csv_import_batch_user_file'
    UNION ALL SELECT 'global', 'unique', 'unique:csv_import_row.uq_csv_import_row_user_account_direction_key', 'csv_import_row', 'uq_csv_import_row_user_account_direction_key'
    UNION ALL SELECT 'global', 'unique', 'unique:tb_reset_snapshot.uq_tb_reset_snapshot_user_path', 'tb_reset_snapshot', 'uq_tb_reset_snapshot_user_path'
    UNION ALL SELECT 'global', 'unique', 'unique:transaction_journal_link.uq_tx_journal_link_user_journal_entry', 'transaction_journal_link', 'uq_tx_journal_link_user_journal_entry'
    UNION ALL SELECT 'global', 'unique', 'unique:transaction_journal_link.uq_tx_journal_link_user_tx', 'transaction_journal_link', 'uq_tx_journal_link_user_tx'
),
deduped AS (
    SELECT scope, artifact_type, artifact_id, table_name, artifact_name
    FROM required
    GROUP BY scope, artifact_type, artifact_id, table_name, artifact_name
),
evaluated AS (
    SELECT
        scope,
        artifact_type,
        artifact_id,
        table_name,
        artifact_name,
        CASE
            WHEN artifact_type = 'table' THEN
                CASE
                    WHEN EXISTS(
                        SELECT 1
                        FROM sqlite_master
                        WHERE type = 'table' AND name = table_name
                    ) THEN 1 ELSE 0
                END
            WHEN artifact_type = 'column' THEN
                CASE
                    WHEN EXISTS(
                        SELECT 1
                        FROM pragma_table_info(table_name)
                        WHERE name = artifact_name
                    ) THEN 1 ELSE 0
                END
            WHEN artifact_type = 'index' THEN
                CASE
                    WHEN EXISTS(
                        SELECT 1
                        FROM pragma_index_list(table_name)
                        WHERE name = artifact_name
                    ) THEN 1 ELSE 0
                END
            WHEN artifact_type = 'unique' THEN
                CASE
                    WHEN EXISTS(
                        SELECT 1
                        FROM sqlite_master
                        WHERE type = 'table'
                          AND name = table_name
                          AND lower(sql) LIKE '%constraint ' || lower(artifact_name) || ' unique%'
                    ) THEN 1 ELSE 0
                END
            WHEN artifact_type = 'check' THEN
                CASE
                    WHEN EXISTS(
                        SELECT 1
                        FROM sqlite_master
                        WHERE type = 'table'
                          AND name = table_name
                          AND lower(sql) LIKE '%constraint ' || lower(artifact_name) || ' check%'
                    ) THEN 1 ELSE 0
                END
            WHEN artifact_type = 'trigger' THEN
                CASE
                    WHEN EXISTS(
                        SELECT 1
                        FROM sqlite_master
                        WHERE type = 'trigger'
                          AND name = artifact_name
                    ) THEN 1 ELSE 0
                END
            ELSE 0
        END AS ok
    FROM deduped
)
SELECT
    scope,
    artifact_type,
    artifact_id,
    ok,
    CASE
        WHEN ok = 1 THEN NULL
        WHEN artifact_type = 'table' THEN 'missing table:' || table_name
        WHEN artifact_type = 'column' THEN 'missing column:' || table_name || '.' || artifact_name
        WHEN artifact_type = 'index' THEN 'missing index:' || table_name || '.' || artifact_name
        WHEN artifact_type = 'unique' THEN 'missing unique:' || table_name || '.' || artifact_name
        WHEN artifact_type = 'check' THEN 'missing check:' || table_name || '.' || artifact_name
        WHEN artifact_type = 'trigger' THEN 'missing trigger:' || artifact_name
        ELSE 'unknown artifact type:' || artifact_type
    END AS message
FROM evaluated
ORDER BY artifact_id;
