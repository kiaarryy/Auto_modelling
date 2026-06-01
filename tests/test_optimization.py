from __future__ import annotations

from auto_fmu.optimization import ParameterSpec, SearchSpace, grid_search


def test_grid_search_records_failed_candidates_and_selects_best() -> None:
    space = SearchSpace([ParameterSpec("gain", 1.0, 3.0, values=(1.0, 2.0, 3.0))])

    def objective(values: dict[str, float]) -> float:
        if values["gain"] == 2.0:
            raise RuntimeError("unstable candidate")
        return abs(values["gain"] - 3.0)

    result = grid_search(space, objective)

    assert result.best.parameters == {"gain": 3.0}
    assert result.best.score == 0.0
    assert len(result.failed_candidates) == 1
    assert "unstable candidate" in result.failed_candidates[0].error


def test_parameter_spec_rejects_out_of_bounds_values() -> None:
    spec = ParameterSpec("gain", 0.0, 1.0)

    assert spec.contains(0.5)
    assert not spec.contains(1.5)
