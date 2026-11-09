"""Legacy scoring entry points backed by the shared evaluation rubric."""
from backend.evaluation import evaluate


def score_scenario(run, scenario):
    return evaluate({'status': 'completed', 'decision': run}, scenario)['score']


def compute_max_score(scenario):
    return 7


def normalize_score(score, scenario):
    return score / 7


def status_of(run, scenario):
    """A strict pass requires component correctness, not a score threshold."""
    if not isinstance(run, dict):
        raise TypeError('Pass/fail requires a decision object; a scalar score is insufficient')
    return bool(evaluate({'status': 'completed', 'decision': run}, scenario)['correct'])
