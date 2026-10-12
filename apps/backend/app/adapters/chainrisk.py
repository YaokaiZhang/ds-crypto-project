"""Integration boundaries. Do not import torch or research trainers in the API."""
from typing import Any
from ..domain import AssessmentContext, CollectedHistory, GraphSample, TaskOutcome, TaskId
from ..errors import FeatureNotImplemented
from ..settings import Settings

class ModelRegistry:
    """Worker-owned approved bundle cache, never per-request training."""
    def __init__(self, settings: Settings):
        self.settings = settings

    def load(self) -> None:
        """Load admitted bundles once, using chainrisk.bundle.load_model_bundle."""
        raise FeatureNotImplemented('models.load')

    def bundle_for(self, task: TaskId) -> Any:
        raise FeatureNotImplemented('models.bundle_for')

    def close(self) -> None:
        """Release resources once real bundle loading is implemented."""

class ChainriskGraphBuilder:
    def build(self, context: AssessmentContext, history: CollectedHistory) -> GraphSample:
        """Use chainrisk.graph.build_graph_sample with the frozen model recipe."""
        raise FeatureNotImplemented('graph.build')

class ChainriskPredictor:
    def __init__(self, registry: ModelRegistry):
        self.registry = registry

    def predict(self, context: AssessmentContext, sample: GraphSample) -> TaskOutcome:
        """Use predict_bundle on this exact sample; never fit or invent scores."""
        raise FeatureNotImplemented('models.predict')

class GraphViewPresenter:
    def present(self, sample: GraphSample, history: CollectedHistory) -> dict[str, Any]:
        """Resolve node_refs/edge_index/lineage; preserve sample identity and cropping."""
        raise FeatureNotImplemented('graph.present')

class RootAnalyticsBuilder:
    def aggregate(self, context: AssessmentContext, history: CollectedHistory) -> dict[str, Any]:
        """Aggregate root/token history with exact units, deduplication and coverage."""
        raise FeatureNotImplemented('analytics.aggregate')
