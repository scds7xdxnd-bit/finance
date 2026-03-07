from __future__ import annotations

"""Multi-label prediction heads."""

from typing import Tuple

import torch
from torch import nn


class MultiLabelHead(nn.Module):
    def __init__(self, input_dim: int, n_labels: int) -> None:
        super().__init__()
        hidden = max(128, input_dim // 2)
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden // 2),
            nn.ReLU(),
            nn.Linear(hidden // 2, n_labels),
        )

    def logits(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return torch.sigmoid(self.logits(x))

    def predict_proba(self, x: torch.Tensor) -> torch.Tensor:
        self.eval()
        with torch.no_grad():
            return self.forward(x)

    def save(self, path: str) -> None:
        torch.save(self.state_dict(), path)

    def load(self, path: str, map_location: str | torch.device = "cpu") -> None:
        state = torch.load(path, map_location=map_location)
        self.load_state_dict(state)


def _compute_pos_weight(labels: torch.Tensor) -> torch.Tensor:
    positives = labels.sum(dim=0)
    total = labels.shape[0]
    pos_weight = torch.ones(labels.shape[1], device=labels.device)
    mask = positives > 0
    pos_weight[mask] = (total - positives[mask]) / positives[mask]
    return pos_weight


def train_multi_label(
    model: MultiLabelHead,
    features: torch.Tensor,
    targets: torch.Tensor,
    epochs: int = 25,
    lr: float = 5e-4,
) -> Tuple[MultiLabelHead, list[float]]:
    pos_weight = _compute_pos_weight(targets)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    history: list[float] = []
    for _ in range(epochs):
        model.train()
        optimizer.zero_grad()
        logits = model.logits(features)
        loss = criterion(logits, targets)
        loss.backward()
        optimizer.step()
        history.append(float(loss.detach().cpu()))
    return model, history


__all__ = ["MultiLabelHead", "train_multi_label"]
