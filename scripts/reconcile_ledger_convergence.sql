-- Reconciliation queries for ledger convergence and money schedule mappings.

-- 1) Transactions missing a linked journal entry.
SELECT COUNT(*) AS unmapped_transactions
FROM "transaction" t
LEFT JOIN transaction_journal_link tjl
  ON tjl.transaction_id = t.id
 AND tjl.user_id = t.user_id
WHERE tjl.id IS NULL;

-- 2) Linked transactions with mismatched journal totals.
WITH journal_totals AS (
    SELECT
        tjl.transaction_id,
        tjl.user_id,
        SUM(CASE WHEN jl.dc = 'D' THEN jl.amount_base ELSE 0 END) AS journal_debit_total,
        SUM(CASE WHEN jl.dc = 'C' THEN jl.amount_base ELSE 0 END) AS journal_credit_total
    FROM transaction_journal_link tjl
    JOIN journal_entry je
      ON je.id = tjl.journal_entry_id
    JOIN journal_line jl
      ON jl.journal_id = je.id
    GROUP BY tjl.transaction_id, tjl.user_id
)
SELECT
    t.id AS transaction_id,
    t.user_id,
    t.debit_amount AS tx_debit,
    t.credit_amount AS tx_credit,
    jt.journal_debit_total,
    jt.journal_credit_total
FROM "transaction" t
JOIN journal_totals jt
  ON jt.transaction_id = t.id
 AND jt.user_id = t.user_id
WHERE ABS(COALESCE(t.debit_amount, 0) - COALESCE(jt.journal_debit_total, 0)) > 0.01
   OR ABS(COALESCE(t.credit_amount, 0) - COALESCE(jt.journal_credit_total, 0)) > 0.01;

-- 3) Money schedule accounts without explicit accounting links.
SELECT
    msa.id AS money_schedule_account_id,
    msa.name,
    msa.currency
FROM money_schedule_accounts msa
LEFT JOIN money_schedule_account_link msal
  ON msal.money_schedule_account_id = msa.id
WHERE msal.id IS NULL;

-- 4) Accounting accounts linked to multiple money schedule accounts (if undesired).
SELECT
    msal.user_id,
    msal.account_id,
    COUNT(*) AS mapping_count
FROM money_schedule_account_link msal
GROUP BY msal.user_id, msal.account_id
HAVING COUNT(*) > 1;
