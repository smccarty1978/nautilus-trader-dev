from research_workflow.generic_collector import GenericStudyCollector
from research_workflow.output_manager import resolve_collection_allowed_feature_aliases
from research_workflow.phase0 import authorize_execution, build_phase0_manifest
from research_workflow.schemas.study_spec import StudySpec


def test_public_workflow_surface_uses_shared_implementations():
    assert GenericStudyCollector.__module__ == "strategies.flip_prediction_collector"
    assert callable(authorize_execution)
    assert callable(build_phase0_manifest)
    assert callable(resolve_collection_allowed_feature_aliases)
    assert StudySpec is not None
