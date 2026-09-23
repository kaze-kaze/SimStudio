from __future__ import annotations

import pytest
from ansys_skill.study.geometry import validate_parameters
from ansys_skill.study.sampling import design_id, plan_samples
from ansys_skill.study.schema import StudySpec
from ansys_skill.study.templates import example_study

pytest.importorskip("scipy")


def test_sampling_is_deterministic_and_partitions_never_share_a_design():
    spec = StudySpec.model_validate(example_study())
    samples, rejected = plan_samples(spec)
    assert (samples, rejected) == plan_samples(spec)
    assert samples[0]["parameters"] == spec.baseline()
    identities = [row["design_id"] for row in samples]
    assert len(identities) == len(set(identities))
    assert sum(row["split"] == "test" for row in samples) == spec.sampling.test_samples
    assert sum(row["split"] == "train" for row in samples) >= spec.sampling.train_samples
    for row in samples:
        validate_parameters(row["parameters"])
    assert rejected and all(item["reason"] for item in rejected)
    assert len(samples) * len(spec.mesh.sizes) <= spec.initial_solver_calls()


def test_a_different_seed_changes_training_and_test_points_but_not_baseline():
    original = StudySpec.model_validate(example_study())
    changed = original.model_copy(deep=True)
    changed.sampling.seed += 10
    first, _ = plan_samples(original)
    second, _ = plan_samples(changed)
    assert first[0] == second[0]
    for split in ("train", "test"):
        assert {s["design_id"] for s in first if s["split"] == split} != {
            s["design_id"] for s in second if s["split"] == split}


def test_dependent_geometry_constraints_exclude_only_invalid_corners():
    spec = StudySpec.model_validate(example_study())
    samples, rejected = plan_samples(spec)
    high = {name: bounds[1] for name, bounds in spec.bounds().items()}
    assert design_id(high) not in {s["design_id"] for s in samples}
    assert any(item["parameters"] == high and "5 mm" in item["reason"] for item in rejected)
    low = {name: bounds[0] for name, bounds in spec.bounds().items()}
    assert design_id(low) in {s["design_id"] for s in samples}


def test_disabling_corners_preserves_explicit_initial_sample_counts():
    document = example_study()
    document["sampling"] = {"train_samples": 6, "test_samples": 3, "include_corners": False}
    spec = StudySpec.model_validate(document)
    samples, _ = plan_samples(spec)
    assert len(samples) == 10
    assert sum(s["split"] == "train" for s in samples) == 6
    assert sum(s["split"] == "test" for s in samples) == 3
