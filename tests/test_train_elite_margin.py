import pytest
import torch

from training.train_elite_margin import a2_rejected_margin_loss, segmented_kl, top3_margin_loss


def batch(actions):
    return {
        "record_options": [(0, 4)],
        "record_actions": [actions],
        "weights": torch.tensor([1.0]),
    }


def test_margin_selects_only_teacher_top3_misses():
    teacher = torch.tensor([3.0, 2.0, 1.0, 0.0])
    student = teacher.clone().requires_grad_(True)
    loss, selected = top3_margin_loss(student, teacher, batch([1]), margin=0.2)
    assert selected == 1
    assert loss.item() > 0
    loss.backward()
    assert student.grad[1] < 0
    assert student.grad[0] > 0
    assert top3_margin_loss(teacher, teacher, batch([0]), margin=0.2)[1] == 0
    assert top3_margin_loss(teacher, teacher, batch([3]), margin=0.2)[1] == 0


def test_segmented_kl_is_zero_for_identical_per_decision_distributions():
    logits = torch.tensor([1.0, 2.0, -3.0, 4.0])
    value = segmented_kl(logits, logits, batch([0]))
    assert abs(value.item()) < 1e-6


def test_a2_err_margin_uses_semantic_group_maxima():
    student = torch.tensor([0.1, 0.9, 0.7, 0.2], requires_grad=True)
    teacher = torch.tensor([2.0, 1.0, 0.0, -1.0])
    semantic_batch = batch([2])
    semantic_batch["record_semantic_groups"] = [[[0, 1], [2, 3]]]
    loss = a2_rejected_margin_loss(student, teacher, semantic_batch, margin=0.2)
    expected = torch.nn.functional.softplus(torch.tensor(0.2 - (0.7 - 0.9)))
    assert float(loss.detach()) == pytest.approx(float(expected))
    loss.backward()
    assert student.grad[2] < 0
    assert student.grad[1] > 0
    assert student.grad[0] == 0
    assert student.grad[3] == 0
