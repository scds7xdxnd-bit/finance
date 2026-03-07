from __future__ import annotations

"""Heads that predict per-account proportions on each side."""

from typing import List, Sequence, Tuple

import torch
from torch import nn


class AccountEmbedding(nn.Module):
    def __init__(self, n_accounts: int, emb_dim: int = 64) -> None:
        super().__init__()
        self.embedding = nn.Embedding(num_embeddings=n_accounts, embedding_dim=emb_dim)

    def forward(self, indices: torch.Tensor) -> torch.Tensor:
        return self.embedding(indices)

    def save(self, path: str) -> None:
        torch.save(self.state_dict(), path)

    def load(self, path: str, map_location: str | torch.device = "cpu") -> None:
        state = torch.load(path, map_location=map_location)
        self.load_state_dict(state)


class ProportionHead(nn.Module):
    def __init__(self, input_dim: int, account_embedding: AccountEmbedding) -> None:
        super().__init__()
        self.account_embedding = account_embedding
        hidden = max(128, input_dim)
        self.net = nn.Sequential(
            nn.Linear(input_dim + account_embedding.embedding.embedding_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden // 2),
            nn.ReLU(),
            nn.Linear(hidden // 2, 1),
        )

    def forward(self, features: torch.Tensor, candidate_indices: torch.Tensor) -> torch.Tensor:
        emb = self.account_embedding(candidate_indices)
        tiled = features.expand(candidate_indices.shape[0], -1)
        logits = self.net(torch.cat([tiled, emb], dim=1)).squeeze(-1)
        return torch.softmax(logits, dim=0)

    def save(self, path: str) -> None:
        torch.save(self.state_dict(), path)

    def load(self, path: str, map_location: str | torch.device = "cpu") -> None:
        state = torch.load(path, map_location=map_location)
        self.load_state_dict(state)


def train_proportion_head(
    model: ProportionHead,
    feature_vectors: torch.Tensor,
    candidate_indices: Sequence[List[int]],
    target_shares: Sequence[List[float]],
    epochs: int = 20,
    lr: float = 1e-3,
) -> Tuple[ProportionHead, List[float]]:
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    history: List[float] = []
    for _ in range(epochs):
        model.train()
        total_loss = 0.0
        for feat, cand, target in zip(feature_vectors, candidate_indices, target_shares):
            if not cand:
                continue
            optimizer.zero_grad()
            cand_tensor = torch.tensor(cand, dtype=torch.long, device=feat.device)
            target_tensor = torch.tensor(target, dtype=torch.float32, device=feat.device)
            preds = model(feat.unsqueeze(0), cand_tensor)
            loss = torch.mean(torch.abs(preds - target_tensor))
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach().cpu())
        history.append(total_loss)
    return model, history


__all__ = ["AccountEmbedding", "ProportionHead", "train_proportion_head"]
