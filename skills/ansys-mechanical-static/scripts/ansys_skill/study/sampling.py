"""Deterministic design points and immutable train/test assignment."""

from __future__ import annotations

from ansys_skill.errors import EnvironmentUnavailableError, SpecValidationError
from ansys_skill.study.schema import FEATURE_NAMES, StudySpec
from ansys_skill.study.storage import canonical_hash


def design_id(parameters: dict[str, float]) -> str:
    return canonical_hash({name: float(format(parameters[name], ".14g"))
                           for name in FEATURE_NAMES})[:20]


def latin_points(bounds: dict[str, list[float]], count: int, seed: int) -> list[dict[str, float]]:
    try:
        from scipy.stats import qmc
    except ImportError as exc:
        raise EnvironmentUnavailableError("Install the 'study' extra for sampling") from exc
    points = qmc.LatinHypercube(d=len(FEATURE_NAMES), rng=seed).random(count)
    return [{name: float(format(bounds[name][0] + row[index] *
                    (bounds[name][1] - bounds[name][0]), ".14g"))
             for index, name in enumerate(FEATURE_NAMES)} for row in points]


def sample_record(parameters: dict[str, float], split: str, *, ordinal: int = 0) -> dict:
    identity = design_id(parameters)
    return {"sample_id": f"{split}-{identity}", "design_id": identity,
            "split": split, "parameters": parameters, "ordinal": ordinal,
            "status": "PLANNED", "geometry": None, "jobs": [], "failure": None}


def plan_samples(spec: StudySpec) -> tuple[list[dict], list[dict]]:
    from ansys_skill.study.geometry import validate_parameters

    baseline = spec.baseline()
    validate_parameters(baseline)
    samples = [sample_record(baseline, "baseline")]
    seen = {design_id(baseline)}
    rejected = []

    def add(parameters, split):
        identity = design_id(parameters)
        try:
            validate_parameters(parameters)
        except SpecValidationError as exc:
            rejected.append({"parameters": parameters, "split": split, "reason": str(exc)})
            return False
        if identity in seen:
            rejected.append({"parameters": parameters, "split": split, "reason": "Duplicate design"})
            return False
        seen.add(identity)
        samples.append(sample_record(parameters, split, ordinal=len(samples)))
        return True

    for offset, split, count in ((0, "train", spec.sampling.train_samples),
                                  (1, "test", spec.sampling.test_samples)):
        accepted = 0
        for parameters in latin_points(spec.bounds(), count, (spec.sampling.seed + offset) % 2**32):
            accepted += add(parameters, split)
        for retry in range(1000):
            if accepted == count:
                break
            point = latin_points(spec.bounds(), 1, (spec.sampling.seed + 10000 + 1000 * offset + retry) % 2**32)[0]
            accepted += add(point, split)
        if accepted != count:
            raise SpecValidationError("Could not fill the constrained design space; revise parameter bounds")
    if spec.sampling.include_corners:
        for parameters in spec.corner_parameters():
            add(parameters, "train")
    return samples, rejected


def initial_samples(spec: StudySpec) -> list[dict]:
    return plan_samples(spec)[0]
