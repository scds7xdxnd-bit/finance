from __future__ import annotations

"""Training and inference pipelines."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import joblib
import numpy as np
import pandas as pd
import torch

from .data_schemas import (
    AggregatedTransaction,
    InferenceInput,
    Suggestion,
    SuggestionLine,
)
from .decoding.greedy_balance import GreedyBalanceDecoder, GreedyDecoderConfig
from .decoding.ilp_balance import HAS_ORTOOLS, ILPBalanceDecoder, ILPDecoderConfig
from .features import FeatureBuilder
from .metrics import (
    compute_gate_metrics,
    compute_multilabel_metrics,
    end_to_end_metrics,
    proportion_mae,
)
from .models import (
    AccountEmbedding,
    BinaryGate,
    MultiLabelHead,
    ProportionHead,
)
from .models.external_pairwise import ExternalPairwisePredictor
from .models.gate_binary import train_binary_gate
from .models.multilabel_heads import train_multi_label
from .models.proportion_head import train_proportion_head
from .preprocessing import build_parent_map, prepare_training_data
from .utils import (
    ExternalPredictorLoader,
    PipelineConfig,
    RulesEngine,
    ensure_dir,
    load_rules,
    load_yaml,
    normalise_probabilities,
    save_yaml,
    set_random_seeds,
)


@dataclass
class ModelArtifacts:
    gate: BinaryGate
    debit_head: MultiLabelHead
    credit_head: MultiLabelHead
    debit_prop: ProportionHead
    credit_prop: ProportionHead
    debit_embedding: AccountEmbedding
    credit_embedding: AccountEmbedding
    feature_builder: FeatureBuilder
    account_to_id: Dict[str, int]
    id_to_account: List[str]
    co_occurrence: Dict[str, Dict[str, float]]
    hierarchy: Dict[str, str]


class Trainer:
    """End-to-end trainer producing persisted artifacts."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config

    def train(
        self,
        train_jsonl: Path,
        out_dir: Path,
        cache_parquet: Optional[Path] = None,
    ) -> Dict[str, float]:
        ensure_dir(out_dir)
        set_random_seeds(self.config.random_seed)

        prepared = prepare_training_data(train_jsonl, cache_parquet)
        df = prepared.dataframe
        feature_builder = FeatureBuilder(text_encoder=self.config.text_encoder)
        feature_mats = feature_builder.fit(df)
        features_np = feature_mats.stack()
        features_tensor = torch.from_numpy(features_np.astype(np.float32))

        account_to_id = {account: idx for idx, account in enumerate(prepared.chart_of_accounts)}
        id_to_account = [account for account in prepared.chart_of_accounts]

        gate_targets = torch.from_numpy(df["is_multiline"].astype(int).to_numpy(dtype=np.float32))

        y_debit = np.zeros((len(df), len(account_to_id)), dtype=np.float32)
        y_credit = np.zeros_like(y_debit)
        debit_candidates: List[List[int]] = []
        credit_candidates: List[List[int]] = []
        debit_shares: List[List[float]] = []
        credit_shares: List[List[float]] = []

        for idx, row in df.iterrows():
            total_amount = float(row["total_amount"]) or 1.0
            debit_ids = [account_to_id[a] for a in row["debit_accounts"]]
            credit_ids = [account_to_id[a] for a in row["credit_accounts"]]
            for acc in debit_ids:
                y_debit[idx, acc] = 1.0
            for acc in credit_ids:
                y_credit[idx, acc] = 1.0
            debit_candidates.append(debit_ids)
            credit_candidates.append(credit_ids)
            debit_shares.append(
                [row["debit_sums_by_account"][id_to_account[a]] / total_amount for a in debit_ids]
                if debit_ids
                else []
            )
            credit_shares.append(
                [row["credit_sums_by_account"][id_to_account[a]] / total_amount for a in credit_ids]
                if credit_ids
                else []
            )

        y_debit_tensor = torch.from_numpy(y_debit)
        y_credit_tensor = torch.from_numpy(y_credit)

        gate_model = BinaryGate(features_np.shape[1])
        gate_model, _ = train_binary_gate(
            gate_model,
            features_tensor,
            gate_targets,
            epochs=self.config.training_epochs,
            lr=self.config.learning_rate,
        )

        debit_head = MultiLabelHead(features_np.shape[1], len(account_to_id))
        debit_head, _ = train_multi_label(
            debit_head,
            features_tensor,
            y_debit_tensor,
            epochs=self.config.training_epochs,
            lr=self.config.learning_rate,
        )
        credit_head = MultiLabelHead(features_np.shape[1], len(account_to_id))
        credit_head, _ = train_multi_label(
            credit_head,
            features_tensor,
            y_credit_tensor,
            epochs=self.config.training_epochs,
            lr=self.config.learning_rate,
        )

        debit_embedding = AccountEmbedding(len(account_to_id))
        credit_embedding = AccountEmbedding(len(account_to_id))
        debit_prop = ProportionHead(features_np.shape[1], debit_embedding)
        credit_prop = ProportionHead(features_np.shape[1], credit_embedding)

        debit_prop, _ = train_proportion_head(
            debit_prop,
            features_tensor,
            debit_candidates,
            debit_shares,
            epochs=max(10, self.config.training_epochs // 2),
            lr=self.config.learning_rate,
        )
        credit_prop, _ = train_proportion_head(
            credit_prop,
            features_tensor,
            credit_candidates,
            credit_shares,
            epochs=max(10, self.config.training_epochs // 2),
            lr=self.config.learning_rate,
        )

        artifacts = ModelArtifacts(
            gate=gate_model,
            debit_head=debit_head,
            credit_head=credit_head,
            debit_prop=debit_prop,
            credit_prop=credit_prop,
            debit_embedding=debit_embedding,
            credit_embedding=credit_embedding,
            feature_builder=feature_builder,
            account_to_id=account_to_id,
            id_to_account=id_to_account,
            co_occurrence=prepared.co_occurrence,
            hierarchy=build_parent_map(id_to_account),
        )

        metrics = self._evaluate(df, features_tensor, artifacts)
        self._persist(out_dir, artifacts, metrics)
        return metrics

    def _evaluate(
        self,
        df: pd.DataFrame,
        features_tensor: torch.Tensor,
        artifacts: ModelArtifacts,
    ) -> Dict[str, float]:
        gate_probs = artifacts.gate.predict_proba(features_tensor).cpu().numpy()
        y_gate = df["is_multiline"].astype(int).to_numpy()
        gate_metrics = compute_gate_metrics(y_gate, gate_probs)

        debit_probs = artifacts.debit_head.predict_proba(features_tensor).cpu().numpy()
        credit_probs = artifacts.credit_head.predict_proba(features_tensor).cpu().numpy()
        y_debit = np.zeros_like(debit_probs)
        y_credit = np.zeros_like(credit_probs)
        for idx, row in df.iterrows():
            for acc in row["debit_accounts"]:
                y_debit[idx, artifacts.account_to_id[acc]] = 1
            for acc in row["credit_accounts"]:
                y_credit[idx, artifacts.account_to_id[acc]] = 1
        debit_metrics = compute_multilabel_metrics(y_debit, debit_probs, threshold=self.config.threshold_debit)
        credit_metrics = compute_multilabel_metrics(y_credit, credit_probs, threshold=self.config.threshold_credit)

        # Proportion MAE on training data.
        debit_pred_shares: List[List[float]] = []
        credit_pred_shares: List[List[float]] = []
        for idx, row in df.iterrows():
            feature = features_tensor[idx].unsqueeze(0)
            debit_ids = [artifacts.account_to_id[a] for a in row["debit_accounts"]]
            credit_ids = [artifacts.account_to_id[a] for a in row["credit_accounts"]]
            if debit_ids:
                preds = artifacts.debit_prop(feature, torch.tensor(debit_ids, dtype=torch.long))
                debit_pred_shares.append(preds.detach().cpu().tolist())
            else:
                debit_pred_shares.append([])
            if credit_ids:
                preds = artifacts.credit_prop(feature, torch.tensor(credit_ids, dtype=torch.long))
                credit_pred_shares.append(preds.detach().cpu().tolist())
            else:
                credit_pred_shares.append([])
        debit_target_shares = [
            [row["debit_sums_by_account"][acc] / row["total_amount"] for acc in row["debit_accounts"]]
            for _, row in df.iterrows()
        ]
        credit_target_shares = [
            [row["credit_sums_by_account"][acc] / row["total_amount"] for acc in row["credit_accounts"]]
            for _, row in df.iterrows()
        ]
        prop_mae = {
            "debit_mae": proportion_mae(debit_target_shares, debit_pred_shares),
            "credit_mae": proportion_mae(credit_target_shares, credit_pred_shares),
        }

        suggestions = self._quick_decode(df, features_tensor, artifacts)
        e2e = end_to_end_metrics(
            [AggregatedTransaction(
                tx_id=row.tx_id,
                date=row.date,
                description=row.description,
                total_amount=row.total_amount,
                debit_accounts=row.debit_accounts,
                credit_accounts=row.credit_accounts,
                debit_sums_by_account=row.debit_sums_by_account,
                credit_sums_by_account=row.credit_sums_by_account,
                is_multiline=row.is_multiline,
                currency=row.currency,
            ) for row in df.itertuples()
            ],
            suggestions,
        )

        metrics = {
            **{f"gate_{k}": v for k, v in gate_metrics.items()},
            **{f"debit_{k}": v for k, v in debit_metrics.items()},
            **{f"credit_{k}": v for k, v in credit_metrics.items()},
            **prop_mae,
            **{f"e2e_{k}": v for k, v in e2e.items()},
        }
        return metrics

    def _quick_decode(
        self,
        df: pd.DataFrame,
        features_tensor: torch.Tensor,
        artifacts: ModelArtifacts,
    ) -> List[Suggestion]:
        decoder = GreedyBalanceDecoder(
            GreedyDecoderConfig(min_amount=self.config.min_line_amount, rounding_unit=self.config.currency_rounding_unit)
        )
        suggestions: List[Suggestion] = []
        debit_probs = artifacts.debit_head.predict_proba(features_tensor).cpu().numpy()
        credit_probs = artifacts.credit_head.predict_proba(features_tensor).cpu().numpy()
        gate_probs = artifacts.gate.predict_proba(features_tensor).cpu().numpy()
        for idx, row in df.iterrows():
            is_multi = gate_probs[idx] >= 0.5
            debit_candidates = _top_accounts(
                row.debit_accounts,
                debit_probs[idx],
                artifacts.id_to_account,
                self.config.max_k_per_side,
            )
            credit_candidates = _top_accounts(
                row.credit_accounts,
                credit_probs[idx],
                artifacts.id_to_account,
                self.config.max_k_per_side,
            )
            candidate_debit_ids = [artifacts.account_to_id[a] for a in debit_candidates]
            candidate_credit_ids = [artifacts.account_to_id[a] for a in credit_candidates]
            feature = features_tensor[idx].unsqueeze(0)
            debit_shares = (
                artifacts.debit_prop(feature, torch.tensor(candidate_debit_ids, dtype=torch.long))
                if candidate_debit_ids
                else torch.tensor([])
            )
            credit_shares = (
                artifacts.credit_prop(feature, torch.tensor(candidate_credit_ids, dtype=torch.long))
                if candidate_credit_ids
                else torch.tensor([])
            )
            debit_dict = {acc: float(val) for acc, val in zip(debit_candidates, debit_shares.tolist())}
            credit_dict = {acc: float(val) for acc, val in zip(credit_candidates, credit_shares.tolist())}
            debit_alloc, credit_alloc = decoder.balance(row.total_amount, debit_dict, credit_dict)
            suggestions.append(
                Suggestion(
                    tx_id=row.tx_id,
                    is_multiline=is_multi,
                    debits=[SuggestionLine(account=a, amount=v) for a, v in debit_alloc.items()],
                    credits=[SuggestionLine(account=a, amount=v) for a, v in credit_alloc.items()],
                    debug_info={},
                )
            )
        return suggestions

    def _persist(self, out_dir: Path, artifacts: ModelArtifacts, metrics: Dict[str, float]) -> None:
        joblib.dump(artifacts.feature_builder, out_dir / "feature_builder.joblib")
        artifacts.gate.save(str(out_dir / "gate.pt"))
        artifacts.debit_head.save(str(out_dir / "debit_head.pt"))
        artifacts.credit_head.save(str(out_dir / "credit_head.pt"))
        artifacts.debit_prop.save(str(out_dir / "debit_prop.pt"))
        artifacts.credit_prop.save(str(out_dir / "credit_prop.pt"))
        artifacts.debit_embedding.save(str(out_dir / "debit_embedding.pt"))
        artifacts.credit_embedding.save(str(out_dir / "credit_embedding.pt"))
        (out_dir / "account_vocab.json").write_text(
            json.dumps(
                {
                    "account_to_id": artifacts.account_to_id,
                    "id_to_account": artifacts.id_to_account,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (out_dir / "co_occurrence.json").write_text(json.dumps(artifacts.co_occurrence, indent=2), encoding="utf-8")
        (out_dir / "hierarchy.json").write_text(json.dumps(artifacts.hierarchy, indent=2), encoding="utf-8")
        (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        save_yaml(out_dir / "config.yaml", self.config.to_dict())


def _top_accounts(
    gold_accounts: Sequence[str],
    prob_vector: np.ndarray,
    id_to_account: Sequence[str],
    max_k: int,
) -> List[str]:
    # Ensure that the gold accounts are at least part of the candidate set when evaluating.
    order = np.argsort(prob_vector)[::-1]
    selected = []
    for idx in order:
        selected.append(id_to_account[idx])
        if len(selected) >= max_k:
            break
    for account in gold_accounts:
        if account not in selected:
            selected.append(account)
    return selected[:max_k]


class InferenceEngine:
    def __init__(
        self,
        model_dir: Path,
        external_module: Optional[str] = None,
    ) -> None:
        self.model_dir = model_dir
        config_payload = load_yaml(model_dir / "config.yaml") if (model_dir / "config.yaml").exists() else {}
        self.config = PipelineConfig.from_dict(config_payload or {})
        self.feature_builder: FeatureBuilder = joblib.load(model_dir / "feature_builder.joblib")
        vocab = json.loads((model_dir / "account_vocab.json").read_text(encoding="utf-8"))
        self.account_to_id: Dict[str, int] = vocab["account_to_id"]
        self.id_to_account: List[str] = vocab["id_to_account"]

        probe = self.feature_builder.transform(pd.DataFrame({
            "description": ["placeholder"],
            "total_amount": [1.0],
            "date": [pd.Timestamp("2024-01-01")],
            "currency": ["USD"],
        })).stack()
        input_dim = probe.shape[1]

        self.gate = BinaryGate(input_dim)
        self.gate.load(str(model_dir / "gate.pt"))
        self.debit_head = MultiLabelHead(input_dim, len(self.account_to_id))
        self.debit_head.load(str(model_dir / "debit_head.pt"))
        self.credit_head = MultiLabelHead(input_dim, len(self.account_to_id))
        self.credit_head.load(str(model_dir / "credit_head.pt"))
        self.debit_embedding = AccountEmbedding(len(self.account_to_id))
        self.debit_embedding.load(str(model_dir / "debit_embedding.pt"))
        self.credit_embedding = AccountEmbedding(len(self.account_to_id))
        self.credit_embedding.load(str(model_dir / "credit_embedding.pt"))
        self.debit_prop = ProportionHead(input_dim, self.debit_embedding)
        self.debit_prop.load(str(model_dir / "debit_prop.pt"))
        self.credit_prop = ProportionHead(input_dim, self.credit_embedding)
        self.credit_prop.load(str(model_dir / "credit_prop.pt"))
        self.gate.eval()
        self.debit_head.eval()
        self.credit_head.eval()
        self.debit_prop.eval()
        self.credit_prop.eval()

        co_path = model_dir / "co_occurrence.json"
        hierarchy_path = model_dir / "hierarchy.json"
        self.co_occurrence = json.loads(co_path.read_text(encoding="utf-8")) if co_path.exists() else {}
        self.hierarchy = json.loads(hierarchy_path.read_text(encoding="utf-8")) if hierarchy_path.exists() else {}
        self.rules_engine: Optional[RulesEngine] = load_rules(Path(self.config.rules_path) if self.config.rules_path else None)
        self.decoder = self._build_decoder()
        self.external_predictor: Optional[ExternalPairwisePredictor] = ExternalPredictorLoader.load(external_module)

    def _build_decoder(self):
        if self.config.decoder == "ilp" and HAS_ORTOOLS:
            return ILPBalanceDecoder(
                ILPDecoderConfig(
                    min_amount=self.config.min_line_amount,
                    rounding_unit=self.config.currency_rounding_unit,
                )
            )
        return GreedyBalanceDecoder(
            GreedyDecoderConfig(
                min_amount=self.config.min_line_amount,
                rounding_unit=self.config.currency_rounding_unit,
            )
        )

    def suggest(self, inputs: Sequence[InferenceInput]) -> List[Suggestion]:
        records = [
            {
                "tx_id": item.tx_id,
                "description": item.description,
                "total_amount": item.total_amount,
                "date": pd.Timestamp(item.date),
                "currency": item.currency or "UNK",
            }
            for item in inputs
        ]
        feature_mats = self.feature_builder.transform(pd.DataFrame(records))
        features_np = feature_mats.stack()
        features_tensor = torch.from_numpy(features_np.astype(np.float32))
        gate_probs = self.gate.predict_proba(features_tensor).cpu().numpy()
        debit_probs_raw = self.debit_head.predict_proba(features_tensor).cpu().numpy()
        credit_probs_raw = self.credit_head.predict_proba(features_tensor).cpu().numpy()

        suggestions: List[Suggestion] = []
        for idx, inference_input in enumerate(inputs):
            feature = features_tensor[idx].unsqueeze(0)
            total_amount = float(inference_input.total_amount)
            known_debits = {entry["account"]: float(entry["amount"]) for entry in inference_input.known_debits}
            known_credits = {entry["account"]: float(entry["amount"]) for entry in inference_input.known_credits}
            remaining_amount = max(
                total_amount - sum(known_debits.values()),
                total_amount - sum(known_credits.values()),
                0.0,
            )

            blended_debit = self._blend_probs(debit_probs_raw[idx], inference_input, side="debit")
            debit_candidates = self._select_candidates(blended_debit, known_debits, side="debit")

            anchor_debit = inference_input.known_debits[0]["account"] if inference_input.known_debits else (debit_candidates[0][0] if debit_candidates else None)
            blended_credit = self._blend_probs(credit_probs_raw[idx], inference_input, side="credit", anchor_account=anchor_debit)
            credit_candidates = self._select_candidates(blended_credit, known_credits, side="credit")

            if self.rules_engine:
                candidate_dict = {
                    "debit": [acc for acc, _ in debit_candidates],
                    "credit": [acc for acc, _ in credit_candidates],
                }
                self.rules_engine.apply(inference_input.description, candidate_dict)
                debit_candidates = self._reconcile_candidates(debit_candidates, candidate_dict["debit"])
                credit_candidates = self._reconcile_candidates(credit_candidates, candidate_dict["credit"])

            debit_shares = self._predict_shares(feature, debit_candidates, side="debit")
            credit_shares = self._predict_shares(feature, credit_candidates, side="credit")

            decoder_debit = {acc: share for acc, share in debit_shares.items() if share > 0}
            decoder_credit = {acc: share for acc, share in credit_shares.items() if share > 0}

            debit_alloc, credit_alloc = self.decoder.balance(remaining_amount, decoder_debit, decoder_credit)

            for account, amount in known_debits.items():
                debit_alloc[account] = debit_alloc.get(account, 0.0) + amount
            for account, amount in known_credits.items():
                credit_alloc[account] = credit_alloc.get(account, 0.0) + amount

            debit_alloc, credit_alloc = self._repair_balance(total_amount, debit_alloc, credit_alloc)

            suggestions.append(
                Suggestion(
                    tx_id=inference_input.tx_id,
                    is_multiline=bool(gate_probs[idx] >= 0.5),
                    debits=[SuggestionLine(account=a, amount=float(v)) for a, v in debit_alloc.items()],
                    credits=[SuggestionLine(account=a, amount=float(v)) for a, v in credit_alloc.items()],
                    debug_info={
                        "p_multiline": float(gate_probs[idx]),
                        "candidates": {
                            "debit": [acc for acc, _ in debit_shares.items()],
                            "credit": [acc for acc, _ in credit_shares.items()],
                        },
                        "shares": {
                            "debit": debit_shares,
                            "credit": credit_shares,
                        },
                        "ranked_suggestions": self._ranked_variations(
                            remaining_amount,
                            debit_shares,
                            credit_shares,
                        ),
                    },
                )
            )
        return suggestions

    def _select_candidates(
        self,
        prob_vector: np.ndarray,
        known_lines: Dict[str, float],
        side: str,
    ) -> List[tuple[str, float]]:
        threshold = self.config.threshold_debit if side == "debit" else self.config.threshold_credit
        candidates: List[tuple[str, float]] = []
        for account, idx in self.account_to_id.items():
            score = float(prob_vector[idx])
            if score >= threshold or account in known_lines:
                candidates.append((account, score))
        candidates.sort(key=lambda item: item[1], reverse=True)
        if not candidates:
            # Fallback to top probability account.
            best_idx = int(prob_vector.argmax())
            account = self.id_to_account[best_idx]
            candidates.append((account, float(prob_vector[best_idx])))
        return candidates[: self.config.max_k_per_side]

    def _reconcile_candidates(
        self,
        baseline: List[tuple[str, float]],
        enforced: Sequence[str],
    ) -> List[tuple[str, float]]:
        lookup = {acc: score for acc, score in baseline}
        for account in enforced:
            if account not in lookup:
                lookup[account] = 0.6  # modest default score
        merged = sorted(lookup.items(), key=lambda item: item[1], reverse=True)
        return merged[: self.config.max_k_per_side]

    def _predict_shares(
        self,
        feature: torch.Tensor,
        candidates: List[tuple[str, float]],
        side: str,
    ) -> Dict[str, float]:
        if not candidates:
            return {}
        ids = [self.account_to_id[acc] for acc, _ in candidates]
        head = self.debit_prop if side == "debit" else self.credit_prop
        shares_tensor = head(feature, torch.tensor(ids, dtype=torch.long)) if candidates else None
        shares = shares_tensor.detach().cpu().numpy().tolist() if shares_tensor is not None else []
        shares = normalise_probabilities(np.asarray(shares, dtype=np.float32)).tolist()
        return {acc: float(share) for acc, share in zip([acc for acc, _ in candidates], shares)}

    def _ranked_variations(
        self,
        total: float,
        debit_shares: Dict[str, float],
        credit_shares: Dict[str, float],
    ) -> List[Dict[str, object]]:
        variations = []
        decoder = GreedyBalanceDecoder(
            GreedyDecoderConfig(
                min_amount=self.config.min_line_amount,
                rounding_unit=self.config.currency_rounding_unit,
            )
        )
        ranked_accounts_debit = list(debit_shares.items())
        ranked_accounts_credit = list(credit_shares.items())
        ranked_accounts_debit.sort(key=lambda item: item[1], reverse=True)
        ranked_accounts_credit.sort(key=lambda item: item[1], reverse=True)

        for drop in range(min(3, len(ranked_accounts_debit))):
            deb_candidates = dict(ranked_accounts_debit[: len(ranked_accounts_debit) - drop])
            credit_candidates = dict(ranked_accounts_credit[: len(ranked_accounts_credit) - drop])
            if not deb_candidates or not credit_candidates:
                continue
            debit_alloc, credit_alloc = decoder.balance(total, deb_candidates, credit_candidates)
            variations.append(
                {
                    "debits": debit_alloc,
                    "credits": credit_alloc,
                }
            )
            if len(variations) >= self.config.top_suggestions:
                break
        return variations

    def _blend_probs(
        self,
        prob_vector: np.ndarray,
        inference_input: InferenceInput,
        side: str,
        anchor_account: Optional[str] = None,
    ) -> np.ndarray:
        blended = prob_vector.copy()
        weight = self.config.blend_external_weight
        if weight <= 0 or not self.external_predictor:
            return blended
        external_scores = np.zeros_like(blended)
        if side == "debit":
            predictions = self.external_predictor.predict_debit(
                inference_input.date.isoformat(),
                inference_input.description,
                inference_input.total_amount,
            )
            for account, score in predictions:
                if account in self.account_to_id:
                    external_scores[self.account_to_id[account]] = score
        else:
            anchor = anchor_account or (inference_input.known_debits[0]["account"] if inference_input.known_debits else "")
            predictions = self.external_predictor.predict_credit(
                inference_input.date.isoformat(),
                inference_input.description,
                anchor,
                inference_input.total_amount,
            )
            for account, score in predictions:
                if account in self.account_to_id:
                    external_scores[self.account_to_id[account]] = score
        if external_scores.sum() > 0:
            external_scores = external_scores / external_scores.max()
            blended = (1 - weight) * blended + weight * external_scores
        return blended

    def _repair_balance(
        self,
        total_amount: float,
        debit_alloc: Dict[str, float],
        credit_alloc: Dict[str, float],
    ) -> Tuple[Dict[str, float], Dict[str, float]]:
        debit_total = sum(debit_alloc.values())
        credit_total = sum(credit_alloc.values())
        if debit_total == 0 or credit_total == 0:
            return debit_alloc, credit_alloc
        # Scale both sides to match requested total.
        scale = total_amount / max(debit_total, credit_total, 1e-6)
        debit_alloc = {acc: amount * scale for acc, amount in debit_alloc.items()}
        credit_alloc = {acc: amount * scale for acc, amount in credit_alloc.items()}
        diff = sum(debit_alloc.values()) - sum(credit_alloc.values())
        if abs(diff) > 1e-4:
            target_side = credit_alloc if diff > 0 else debit_alloc
            if target_side:
                target = max(target_side, key=target_side.get)
                target_side[target] += -diff
        return debit_alloc, credit_alloc


__all__ = ["Trainer", "InferenceEngine", "ModelArtifacts"]
