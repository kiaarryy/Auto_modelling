from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Callable, Iterable, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    lower: float
    upper: float
    values: Tuple[float, ...] = ()

    def contains(self, value: float) -> bool:
        return self.lower <= float(value) <= self.upper

    def candidates(self) -> Tuple[float, ...]:
        values = self.values or (self.lower, self.upper)
        if not all(self.contains(value) for value in values):
            raise ValueError(f"{self.name} includes an out-of-bounds candidate")
        return tuple(float(value) for value in values)


@dataclass(frozen=True)
class SearchSpace:
    parameters: Sequence[ParameterSpec]


@dataclass(frozen=True)
class CandidateResult:
    parameters: dict[str, float]
    score: Optional[float]
    error: str = ""


@dataclass(frozen=True)
class OptimizationResult:
    best: CandidateResult
    candidates: Tuple[CandidateResult, ...]

    @property
    def failed_candidates(self) -> Tuple[CandidateResult, ...]:
        return tuple(candidate for candidate in self.candidates if candidate.error)


def grid_search(space: SearchSpace, objective: Callable[[dict[str, float]], float]) -> OptimizationResult:
    names = [spec.name for spec in space.parameters]
    combinations: Iterable[Tuple[float, ...]] = product(*(spec.candidates() for spec in space.parameters))
    results = []
    for combination in combinations:
        parameters = dict(zip(names, combination))
        try:
            score = float(objective(parameters))
            results.append(CandidateResult(parameters=parameters, score=score))
        except Exception as exc:  # Candidate failures are evidence, not batch failures.
            results.append(CandidateResult(parameters=parameters, score=None, error=str(exc)))
    successful = [candidate for candidate in results if candidate.score is not None]
    if not successful:
        raise RuntimeError("all optimization candidates failed")
    best = min(successful, key=lambda candidate: float(candidate.score))
    return OptimizationResult(best=best, candidates=tuple(results))
