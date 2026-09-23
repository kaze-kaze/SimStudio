"""Independent numerical agreement with a maintained reference implementation."""
from __future__ import annotations

import pytest
from ansys_skill.surrogate.models import _fit_gpr, _predict_numeric_model

np = pytest.importorskip("numpy")
pytest.importorskip("sklearn")


@pytest.mark.parametrize("name", ["rbf", "matern32", "matern52"])
def test_json_gp_core_agrees_with_sklearn_fixed_kernel(name):
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, Matern

    x = np.array([[0.0, 0.0], [0.2, 0.8], [0.5, 0.3], [0.8, 0.9], [1.0, 0.2]])
    y = 2e-5 + 1e-5 * np.sin(x[:, 0] * 3) + 0.4e-5 * x[:, 1] ** 2
    query = np.array([[0.12, 0.17], [0.47, 0.41], [0.95, 0.85]])
    length = 0.5
    kernel = RBF(length) if name == "rbf" else Matern(length, nu=1.5 if name == "matern32" else 2.5)
    actual_model = _fit_gpr(np, x, y, name, length)
    reference = GaussianProcessRegressor(kernel=kernel, alpha=actual_model["jitter"],
                                         optimizer=None, normalize_y=True).fit(x, y)
    mean, std = _predict_numeric_model(np, actual_model, query)
    expected_mean, expected_std = reference.predict(query, return_std=True)
    np.testing.assert_allclose(mean, expected_mean, rtol=1e-9, atol=1e-14)
    np.testing.assert_allclose(std, expected_std, rtol=1e-8, atol=1e-14)
