from research_workflow.grammar.spec import ChronologySpec
from research_workflow.replay_closure import reuse_policy, SHADOW_SAMPLED_ONE_IN

def test_new_default_sampled_and_explicit_every_run_preserved():
    assert ChronologySpec(train=[2020]).partition_reuse_shadow == 'sampled'
    assert ChronologySpec(train=[2020], partition_reuse_shadow='every_run').partition_reuse_shadow == 'every_run'
    assert SHADOW_SAMPLED_ONE_IN == 4
    assert reuse_policy({})['shadow'] == 'every_run'
