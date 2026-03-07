"""CLI command registration."""

def register_cli(app):
    from finance_app.cli.management import (
        assign_account_ids_cli,
        assign_codes_cli,
        backfill_transaction_links_cli,
        ledger_convergence_metrics_cli,
        ledger_reconcile_cli,
        merge_accounts_cli,
        migrate_to_journal_cli,
        money_schedule_fill_cli,
        prune_hints_cli,
        schema_status_cli,
        sqlite_backup_cli,
        tb_reset_restore_cli,
        upgrade_schema_cli,
    )

    app.cli.add_command(migrate_to_journal_cli)
    app.cli.add_command(merge_accounts_cli)
    app.cli.add_command(upgrade_schema_cli)
    app.cli.add_command(schema_status_cli)
    app.cli.add_command(sqlite_backup_cli)
    app.cli.add_command(prune_hints_cli)
    app.cli.add_command(assign_account_ids_cli)
    app.cli.add_command(assign_codes_cli)
    app.cli.add_command(money_schedule_fill_cli)
    app.cli.add_command(ledger_convergence_metrics_cli)
    app.cli.add_command(backfill_transaction_links_cli)
    app.cli.add_command(ledger_reconcile_cli)
    app.cli.add_command(tb_reset_restore_cli)
