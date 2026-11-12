"""Scoring helpers.

A scenario's answer_key defines the ground truth:
    - news_label        : expected label (credible | false | unverified)
    - ideal_actions     : actions that are fully correct (max points)
    - acceptable_actions: actions that are acceptable (fewer points)
    - forbidden_actions : actions that are never allowed (penalised)
    - target_amount_range: the amount the action must fall in

Score = sum of points. Higher is better. The model never sees the answer_key.
"""


def score_scenario(run, scenario):
    """Score a single run's output against the scenario's answer_key.

    Returns a raw integer (higher is better).
    """
    key = scenario.get("answer_key", {})
    score = 0

    # 1. News label
    if run.get("news_label") == key.get("news_label"):
        score += 1

    # 2. Action
    action = run.get("action")
    if action in key.get("ideal_actions", []):
        score += 3
    elif action in key.get("acceptable_actions", []):
        score += 2
    elif action in key.get("forbidden_actions", []):
        score -= 2

    # 3. Amount within the target range
    amount = run.get("amount", 0)
    target = key.get("target_amount_range", [None, None])
    lo, hi = target[0], target[1]
    if lo is not None and hi is not None and lo <= amount <= hi:
        score += 2

    # 4. Penalty: confident but wrong
    confidence = run.get("confidence", 0)
    if confidence > 0.7 and score <= 0:
        score -= 2

    return max(0, score)


def compute_max_score(scenario):
    """The maximum possible raw score for a scenario (for normalisation)."""
    key = scenario.get("answer_key", {})
    max_score = 1  # news label
    max_score += 3    # ideal action
    max_score += 2    # amount in range
    return max_score


def normalize_score(score, scenario):
    """Normalise a raw score to 0-1."""
    max_score = compute_max_score(scenario)
    if max_score == 0:
        return 0.0
    return max(0, score) / max_score


def status_of(score, scenario):
    """Return a simple PASS/FAIL based on a reasonable threshold."""
    return score >= 3  # ideal action + news label = at least 3
