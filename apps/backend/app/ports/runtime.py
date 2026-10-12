from typing import Protocol, Any
from ..domain import AssessmentContext, CollectedHistory, GraphSample, TaskOutcome

class GraphBuilder(Protocol):
    def build(self, context: AssessmentContext, history: CollectedHistory) -> GraphSample: ...

class Predictor(Protocol):
    def predict(self, context: AssessmentContext, sample: GraphSample) -> TaskOutcome: ...

class GraphPresenter(Protocol):
    def present(self, sample: GraphSample, history: CollectedHistory) -> dict[str, Any]: ...

class AnalyticsBuilder(Protocol):
    def aggregate(self, context: AssessmentContext, history: CollectedHistory) -> dict[str, Any]: ...
