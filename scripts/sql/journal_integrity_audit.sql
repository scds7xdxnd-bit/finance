-- SSOT 90.8 preflight checks for journal_integrity rollout.
-- Any returned row indicates blocking data violations that must be remediated
-- before applying integrity-enforcement migrations.

-- 1) Invalid debit/credit direction values.
SELECT
  id,
  journal_id,
  dc
FROM journal_line
WHERE dc IS NULL
   OR dc NOT IN ('D', 'C');

-- 2) Unbalanced finalized journal entries.
SELECT
  j.id AS journal_entry_id
FROM journal_entry AS j
LEFT JOIN journal_line AS l ON l.journal_id = j.id
WHERE j.posted_at IS NOT NULL
GROUP BY j.id
HAVING ROUND(COALESCE(SUM(CASE WHEN l.dc = 'D' THEN l.amount_base ELSE 0 END), 0), 2)
    != ROUND(COALESCE(SUM(CASE WHEN l.dc = 'C' THEN l.amount_base ELSE 0 END), 0), 2);
