-- SQLite schema capability verification for vNext.
-- Usage:
--   sqlite3 /path/to/db.sqlite < scripts/verify_schema_capabilities.sql

WITH checks(capability, check_name, ok) AS (
    -- tx_linking
    SELECT 'tx_linking', 'table:transaction_journal_link',
           EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'transaction_journal_link')
    UNION ALL
    SELECT 'tx_linking', 'column:transaction_journal_link.source',
           EXISTS(SELECT 1 FROM pragma_table_info('transaction_journal_link') WHERE name = 'source')
    UNION ALL
    SELECT 'tx_linking', 'index:transaction_journal_link.ix_tx_journal_link_user_journal',
           EXISTS(SELECT 1 FROM pragma_index_list('transaction_journal_link') WHERE name = 'ix_tx_journal_link_user_journal')
    UNION ALL
    SELECT 'tx_linking', 'index:transaction_journal_link.ix_tx_journal_link_user_source',
           EXISTS(SELECT 1 FROM pragma_index_list('transaction_journal_link') WHERE name = 'ix_tx_journal_link_user_source')
    UNION ALL
    SELECT 'tx_linking', 'unique:transaction_journal_link.uq_tx_journal_link_user_tx',
           EXISTS(
               SELECT 1
               FROM sqlite_master
               WHERE type = 'table'
                 AND name = 'transaction_journal_link'
                 AND lower(sql) LIKE '%constraint uq_tx_journal_link_user_tx unique%'
           )
    UNION ALL
    SELECT 'tx_linking', 'unique:transaction_journal_link.uq_tx_journal_link_user_journal_entry',
           EXISTS(
               SELECT 1
               FROM sqlite_master
               WHERE type = 'table'
                 AND name = 'transaction_journal_link'
                 AND lower(sql) LIKE '%constraint uq_tx_journal_link_user_journal_entry unique%'
           )
    UNION ALL
    SELECT 'tx_linking', 'check:transaction_journal_link.ck_tx_journal_link_source_nonempty',
           EXISTS(
               SELECT 1
               FROM sqlite_master
               WHERE type = 'table'
                 AND name = 'transaction_journal_link'
                 AND lower(sql) LIKE '%constraint ck_tx_journal_link_source_nonempty check%'
           )

    UNION ALL
    -- link_candidates
    SELECT 'link_candidates', 'table:transaction_link_candidate',
           EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'transaction_link_candidate')
    UNION ALL
    SELECT 'link_candidates', 'index:transaction_link_candidate.ix_tx_link_candidate_user_status',
           EXISTS(SELECT 1 FROM pragma_index_list('transaction_link_candidate') WHERE name = 'ix_tx_link_candidate_user_status')
    UNION ALL
    SELECT 'link_candidates', 'index:transaction_link_candidate.ix_tx_link_candidate_user_tx_reason',
           EXISTS(SELECT 1 FROM pragma_index_list('transaction_link_candidate') WHERE name = 'ix_tx_link_candidate_user_tx_reason')
    UNION ALL
    SELECT 'link_candidates', 'check:transaction_link_candidate.ck_tx_link_candidate_source_nonempty',
           EXISTS(
               SELECT 1
               FROM sqlite_master
               WHERE type = 'table'
                 AND name = 'transaction_link_candidate'
                 AND lower(sql) LIKE '%constraint ck_tx_link_candidate_source_nonempty check%'
           )

    UNION ALL
    -- csv_idempotency
    SELECT 'csv_idempotency', 'table:csv_import_batch',
           EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'csv_import_batch')
    UNION ALL
    SELECT 'csv_idempotency', 'table:csv_import_row',
           EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'csv_import_row')
    UNION ALL
    SELECT 'csv_idempotency', 'unique:csv_import_batch.uq_csv_import_batch_user_file',
           EXISTS(
               SELECT 1
               FROM sqlite_master
               WHERE type = 'table'
                 AND name = 'csv_import_batch'
                 AND lower(sql) LIKE '%constraint uq_csv_import_batch_user_file unique%'
           )
    UNION ALL
    SELECT 'csv_idempotency', 'unique:csv_import_row.uq_csv_import_row_user_account_direction_key',
           EXISTS(
               SELECT 1
               FROM sqlite_master
               WHERE type = 'table'
                 AND name = 'csv_import_row'
                 AND lower(sql) LIKE '%constraint uq_csv_import_row_user_account_direction_key unique%'
           )
    UNION ALL
    SELECT 'csv_idempotency', 'check:csv_import_batch.ck_csv_import_batch_status',
           EXISTS(
               SELECT 1
               FROM sqlite_master
               WHERE type = 'table'
                 AND name = 'csv_import_batch'
                 AND lower(sql) LIKE '%constraint ck_csv_import_batch_status check%'
           )
    UNION ALL
    SELECT 'csv_idempotency', 'check:csv_import_row.ck_csv_import_row_direction',
           EXISTS(
               SELECT 1
               FROM sqlite_master
               WHERE type = 'table'
                 AND name = 'csv_import_row'
                 AND lower(sql) LIKE '%constraint ck_csv_import_row_direction check%'
           )
    UNION ALL
    SELECT 'csv_idempotency', 'index:csv_import_row.ix_csv_import_row_user_status',
           EXISTS(SELECT 1 FROM pragma_index_list('csv_import_row') WHERE name = 'ix_csv_import_row_user_status')

    UNION ALL
    -- tb_snapshot
    SELECT 'tb_snapshot', 'table:tb_reset_snapshot',
           EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tb_reset_snapshot')
    UNION ALL
    SELECT 'tb_snapshot', 'column:tb_reset_snapshot.db_copy_path',
           EXISTS(SELECT 1 FROM pragma_table_info('tb_reset_snapshot') WHERE name = 'db_copy_path')
    UNION ALL
    SELECT 'tb_snapshot', 'column:tb_reset_snapshot.sha256',
           EXISTS(SELECT 1 FROM pragma_table_info('tb_reset_snapshot') WHERE name = 'sha256')
    UNION ALL
    SELECT 'tb_snapshot', 'column:tb_reset_snapshot.restore_status',
           EXISTS(SELECT 1 FROM pragma_table_info('tb_reset_snapshot') WHERE name = 'restore_status')
    UNION ALL
    SELECT 'tb_snapshot', 'column:tb_reset_snapshot.file_size_bytes',
           EXISTS(SELECT 1 FROM pragma_table_info('tb_reset_snapshot') WHERE name = 'file_size_bytes')
    UNION ALL
    SELECT 'tb_snapshot', 'unique:tb_reset_snapshot.uq_tb_reset_snapshot_user_path',
           EXISTS(
               SELECT 1
               FROM sqlite_master
               WHERE type = 'table'
                 AND name = 'tb_reset_snapshot'
                 AND lower(sql) LIKE '%constraint uq_tb_reset_snapshot_user_path unique%'
           )
    UNION ALL
    SELECT 'tb_snapshot', 'check:tb_reset_snapshot.ck_tb_reset_snapshot_sha256_len',
           EXISTS(
               SELECT 1
               FROM sqlite_master
               WHERE type = 'table'
                 AND name = 'tb_reset_snapshot'
                 AND lower(sql) LIKE '%constraint ck_tb_reset_snapshot_sha256_len check%'
           )
    UNION ALL
    SELECT 'tb_snapshot', 'check:tb_reset_snapshot.ck_tb_reset_snapshot_file_size_nonneg',
           EXISTS(
               SELECT 1
               FROM sqlite_master
               WHERE type = 'table'
                 AND name = 'tb_reset_snapshot'
                 AND lower(sql) LIKE '%constraint ck_tb_reset_snapshot_file_size_nonneg check%'
           )
    UNION ALL
    SELECT 'tb_snapshot', 'check:tb_reset_snapshot.ck_tb_reset_snapshot_restore_status',
           EXISTS(
               SELECT 1
               FROM sqlite_master
               WHERE type = 'table'
                 AND name = 'tb_reset_snapshot'
                 AND lower(sql) LIKE '%constraint ck_tb_reset_snapshot_restore_status check%'
           )
    UNION ALL
    SELECT 'tb_snapshot', 'index:tb_reset_snapshot.ix_tb_reset_snapshot_user_created',
           EXISTS(SELECT 1 FROM pragma_index_list('tb_reset_snapshot') WHERE name = 'ix_tb_reset_snapshot_user_created')

    UNION ALL
    -- admin_audit
    SELECT 'admin_audit', 'table:admin_action_audit',
           EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'admin_action_audit')
    UNION ALL
    SELECT 'admin_audit', 'index:admin_action_audit.ix_admin_action_audit_actor_created',
           EXISTS(SELECT 1 FROM pragma_index_list('admin_action_audit') WHERE name = 'ix_admin_action_audit_actor_created')

    UNION ALL
    -- journal_report_perf
    SELECT 'journal_report_perf', 'index:journal_entry.ix_journal_entry_user_date_parsed',
           EXISTS(SELECT 1 FROM pragma_index_list('journal_entry') WHERE name = 'ix_journal_entry_user_date_parsed')
    UNION ALL
    SELECT 'journal_report_perf', 'index:journal_entry.ix_journal_entry_user_reference',
           EXISTS(SELECT 1 FROM pragma_index_list('journal_entry') WHERE name = 'ix_journal_entry_user_reference')
    UNION ALL
    SELECT 'journal_report_perf', 'index:journal_line.ix_journal_line_journal_account_dc',
           EXISTS(SELECT 1 FROM pragma_index_list('journal_line') WHERE name = 'ix_journal_line_journal_account_dc')
    UNION ALL
    SELECT 'journal_report_perf', 'index:journal_line.ix_journal_line_account_dc_journal',
           EXISTS(SELECT 1 FROM pragma_index_list('journal_line') WHERE name = 'ix_journal_line_account_dc_journal')
)
SELECT capability, check_name, ok
FROM checks
ORDER BY capability, check_name;
