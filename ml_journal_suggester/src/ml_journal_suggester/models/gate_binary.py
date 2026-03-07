from __future__ import annotations

"""Binary gate that decides whether a transaction is multi-line."""

from typing import Tuple

import torch
from torch import nn


class BinaryGate(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int = 128) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(hidden_dim // 2, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        logits = self.net(x)
        return torch.sigmoid(logits).squeeze(-1)

    def predict_proba(self, x: torch.Tensor) -> torch.Tensor:
        self.eval()
        with torch.no_grad():
            return self.forward(x)

    def save(self, path: str) -> None:
        torch.save(self.state_dict(), path)

    def load(self, path: str, map_location: str | torch.device = "cpu") -> None:
        state = torch.load(path, map_location=map_location)
        self.load_state_dict(state)


def train_binary_gate(
    model: BinaryGate,
    features: torch.Tensor,
    targets: torch.Tensor,
    epochs: int = 20,
    lr: float = 1e-3,
) -> Tuple[BinaryGate, list[float]]:
    criterion = nn.BCELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    history: list[float] = []
    for epoch in range(epochs):
        model.train()
        optimizer.zero_grad()
        preds = model(features)
        loss = criterion(preds, targets)
        loss.backward()
        optimizer.step()
        history.append(float(loss.detach().cpu()))
    return model, history


__all__ = ["BinaryGate", "train_binary_gate"]
