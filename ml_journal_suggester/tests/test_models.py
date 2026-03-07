import torch
from ml_journal_suggester.models.gate_binary import BinaryGate, train_binary_gate
from ml_journal_suggester.models.multilabel_heads import MultiLabelHead, train_multi_label
from ml_journal_suggester.models.proportion_head import AccountEmbedding, ProportionHead, train_proportion_head


def test_binary_gate_training_reduces_loss() -> None:
    torch.manual_seed(0)
    features = torch.randn(32, 10)
    targets = (features[:, 0] > 0).float()
    model = BinaryGate(input_dim=10)
    _, history = train_binary_gate(model, features, targets, epochs=10, lr=1e-2)
    assert len(history) == 10
    assert history[-1] <= history[0] + 1e-6 or history[-1] < history[0]


def test_multilabel_head_shape() -> None:
    torch.manual_seed(1)
    features = torch.randn(16, 8)
    targets = torch.zeros(16, 5)
    targets[:, 0] = (features[:, 0] > 0).float()
    targets[:, 1] = (features[:, 1] > 0).float()
    head = MultiLabelHead(8, 5)
    trained, _ = train_multi_label(head, features, targets, epochs=5, lr=1e-2)
    probs = trained.predict_proba(features)
    assert probs.shape == (16, 5)
    assert torch.all((probs >= 0) & (probs <= 1))


def test_proportion_head_softmax() -> None:
    features = torch.randn(6, 12)
    embedding = AccountEmbedding(n_accounts=7, emb_dim=8)
    head = ProportionHead(12, embedding)
    candidates = [[0, 1, 2], [3, 4], [], [5, 6], [0], [1, 3]]
    shares = [[0.5, 0.3, 0.2], [0.7, 0.3], [], [0.6, 0.4], [1.0], [0.2, 0.8]]
    train_proportion_head(head, features, candidates, shares, epochs=3, lr=1e-2)
    cand_tensor = torch.tensor([0, 1, 2], dtype=torch.long)
    preds = head(features[0].unsqueeze(0), cand_tensor)
    assert torch.isclose(preds.sum(), torch.tensor(1.0), atol=1e-5)
