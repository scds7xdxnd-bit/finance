"""Lightweight journal suggester runtime model and state handling."""

from __future__ import annotations


class JournalModel:
    def __init__(self):
        # Initialize model parameters and load weights if available.
        self.feedback_counts = {"accept": 0, "reject": 0}
        # Nested mapping: {account_a: {account_b: count}}, account_a < account_b.
        self.account_cooccurrence = {}
        self.account_embeddings = {}
        self._load_state()

    def _state_dir(self):
        import os

        try:
            from flask import current_app

            base_dir = current_app.instance_path
        except Exception:
            base_dir = os.path.abspath(
                os.path.join(os.path.dirname(__file__), os.pardir, "instance")
            )
        state_dir = os.path.join(base_dir, "ml_state")
        os.makedirs(state_dir, exist_ok=True)
        return state_dir

    def _state_path(self):
        import os

        return os.path.join(self._state_dir(), "journal_state.json")

    def _embeds_path(self):
        import os

        return os.path.join(self._state_dir(), "account_embeds.json")

    def _atomic_write_json(self, path, payload):
        import json
        import os
        import tempfile

        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=True, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
            try:
                dir_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except Exception:
                pass
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            raise

    def _normalise_pair(self, account_a, account_b):
        a = (account_a or "").strip()
        b = (account_b or "").strip()
        if not a or not b:
            return None
        if a == b:
            return None
        return tuple(sorted((a, b)))

    def _bump_pair(self, account_a, account_b, delta=1):
        pair = self._normalise_pair(account_a, account_b)
        if not pair:
            return
        a, b = pair
        bucket = self.account_cooccurrence.setdefault(a, {})
        try:
            inc = int(delta)
        except Exception:
            inc = 0
        try:
            current = int(bucket.get(b, 0) or 0)
        except Exception:
            current = 0
        new_count = current + inc
        if new_count > 0:
            bucket[b] = new_count
        elif b in bucket:
            del bucket[b]
        if not bucket and a in self.account_cooccurrence:
            del self.account_cooccurrence[a]

    def _iter_pairs(self):
        for account_a, related in self.account_cooccurrence.items():
            if not isinstance(related, dict):
                continue
            for account_b, count in related.items():
                try:
                    weight = float(count)
                except Exception:
                    continue
                if weight <= 0:
                    continue
                yield account_a, account_b, weight

    def _parse_legacy_pair_key(self, raw_key):
        import ast

        key = str(raw_key)
        try:
            parsed = ast.literal_eval(key)
            if isinstance(parsed, (tuple, list)) and len(parsed) == 2:
                return str(parsed[0]), str(parsed[1])
        except Exception:
            pass
        for sep in ("|||", "||", "::", "<->", "|"):
            if sep in key:
                left, right = key.split(sep, 1)
                return left.strip(), right.strip()
        return None, None

    def _normalise_cooccurrence(self, value):
        normalized = {}
        if not isinstance(value, dict):
            return normalized
        for account_a, related in value.items():
            if isinstance(related, dict):
                for account_b, count in related.items():
                    try:
                        c = int(count)
                    except Exception:
                        continue
                    pair = self._normalise_pair(account_a, account_b)
                    if not pair or c <= 0:
                        continue
                    left, right = pair
                    normalized.setdefault(left, {})[right] = c
                continue
            legacy_a, legacy_b = self._parse_legacy_pair_key(account_a)
            if not legacy_a or not legacy_b:
                continue
            try:
                c = int(related)
            except Exception:
                continue
            pair = self._normalise_pair(legacy_a, legacy_b)
            if not pair or c <= 0:
                continue
            left, right = pair
            normalized.setdefault(left, {})[right] = c
        return normalized

    def _load_state(self):
        import json
        import os

        path = self._state_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                return
            feedback = payload.get("feedback_counts")
            if isinstance(feedback, dict):
                try:
                    self.feedback_counts["accept"] = int(
                        feedback.get("accept", self.feedback_counts["accept"]) or 0
                    )
                except Exception:
                    pass
                try:
                    self.feedback_counts["reject"] = int(
                        feedback.get("reject", self.feedback_counts["reject"]) or 0
                    )
                except Exception:
                    pass
            self.account_cooccurrence = self._normalise_cooccurrence(
                payload.get("account_cooccurrence", {})
            )
        except Exception:
            # Keep defaults if state file is missing/corrupt.
            pass

    def _save_state(self):
        payload = {
            "feedback_counts": {
                "accept": int(self.feedback_counts.get("accept", 0) or 0),
                "reject": int(self.feedback_counts.get("reject", 0) or 0),
            },
            "account_cooccurrence": self._normalise_cooccurrence(
                self.account_cooccurrence
            ),
        }
        try:
            self._atomic_write_json(self._state_path(), payload)
        except Exception:
            pass

    def propose_balanced_journals(self, input_data):
        """
        Propose full balanced journal drafts based on the provided input data.
        This stub implementation should:
        1. Ingest descriptions, amounts, and historical patterns to propose drafts.
        2. Use account embeddings learned from prior postings.
        3. Incorporate temporal and contextual signals (period, vendor, project).
        4. Adapt using feedback from journal editor.
        5. Ensure suggestions are balanced (debit/credit sum zero).

        :param input_data: dict with relevant transaction/journal input data
        :return: list of balanced journal drafts
        """
        # Stub: Return a sample balanced journal draft
        sample_draft = {
            'entries': [
                {'account': 'Cash', 'debit': 1000, 'credit': 0},
                {'account': 'Revenue', 'debit': 0, 'credit': 1000}
            ],
            'notes': 'Sample balanced journal entry generated by ML model'
        }
        return [sample_draft]

    def update_with_feedback(self, feedback):
        """
        Update the lightweight model with editor feedback.
        Expected feedback format:
          { 'user_id': int, 'accepted': true/false, 'suggestion': { 'entries': [...] }, 'context': { ... } }
        This stub will update simple counters and co-occurrence counts for accounts appearing together.
        """
        try:
            accepted = bool(feedback.get('accepted'))
            if accepted:
                self.feedback_counts['accept'] += 1
            else:
                self.feedback_counts['reject'] += 1
            suggestion = feedback.get('suggestion') or {}
            entries = suggestion.get('entries') or []
            accounts = [e.get('account') for e in entries if e.get('account')]
            # update cooccurrence
            for i, account_a in enumerate(accounts):
                for account_b in accounts[i + 1 :]:
                    self._bump_pair(account_a, account_b, 1 if accepted else 0)
            self._save_state()
            # Possibly trigger lightweight incremental training
            try:
                train_res = self.maybe_train_on_feedback()
            except Exception:
                train_res = {"ok": False}
            return {"ok": True, "saved": True, "train": train_res}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def train_incremental_mf(self, epochs=5, factors=8, reg=0.1):
        """
        Lightweight incremental matrix factorization on the account cooccurrence counts.
        This builds embeddings for accounts using simple alternating least squares (ALS)-style updates.
        The method is intentionally small and depends only on numpy.
        """
        try:
            import numpy as np
            # Build index mapping
            keys = list(self._iter_pairs())
            accounts = set()
            for account_a, account_b, _ in keys:
                accounts.add(account_a)
                accounts.add(account_b)
            accounts = sorted(accounts)
            if not accounts:
                return {"ok": False, "error": "No accounts to train on"}
            idx = {account: i for i, account in enumerate(accounts)}
            n = len(accounts)
            # Build symmetric cooccurrence matrix
            M = np.zeros((n, n), dtype=float)
            for account_a, account_b, count in keys:
                if account_a in idx and account_b in idx:
                    i, j = idx[account_a], idx[account_b]
                    M[i, j] = count
                    M[j, i] = count
            # Initialize embeddings
            X = np.random.normal(scale=0.01, size=(n, factors))
            Y = np.random.normal(scale=0.01, size=(n, factors))
            I = np.eye(factors)
            for _ in range(epochs):
                # Update X
                for i in range(n):
                    # Solve (Y^T W Y + reg I) x = Y^T W m
                    w = M[i, :]
                    W = np.diag(w)
                    A = Y.T @ W @ Y + reg * I
                    b = Y.T @ (W @ M[i, :])
                    # Regularize
                    try:
                        X[i, :] = np.linalg.solve(A, b)
                    except np.linalg.LinAlgError:
                        X[i, :] = np.linalg.lstsq(A, b, rcond=None)[0]
                # Update Y symmetrically
                for j in range(n):
                    w = M[:, j]
                    W = np.diag(w)
                    A = X.T @ W @ X + reg * I
                    b = X.T @ (W @ M[:, j])
                    try:
                        Y[j, :] = np.linalg.solve(A, b)
                    except np.linalg.LinAlgError:
                        Y[j, :] = np.linalg.lstsq(A, b, rcond=None)[0]
            # Save embeddings mapping
            emb = {account: X[idx[account]].tolist() for account in accounts}
            self._atomic_write_json(
                self._embeds_path(),
                {"accounts": accounts, "embeddings": emb},
            )
            self.account_embeddings = emb
            return {"ok": True, "trained_on": len(accounts)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def maybe_train_on_feedback(self, threshold=5):
        """
        Trigger incremental trainer when accepted feedback count reaches threshold since last training.
        For this stub, we'll use feedback_counts['accept'] as a crude trigger and then reset a counter.
        """
        try:
            # Use accept count as trigger
            if self.feedback_counts.get("accept", 0) >= threshold:
                res = self.train_incremental_mf()
                # reset accept counter
                self.feedback_counts["accept"] = 0
                self._save_state()
                return res
            return {"ok": False, "reason": "threshold not reached"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
