"""Controlled evidence fixtures for experiments; no live news retrieval.

news_sources is authored by the scenario designer, never extracted from the trigger.
Each record: source_id, independence_group, trusted (bool), verdict
(supports/refutes/unknown), content. Two independent trusted records are required.
"""
from copy import deepcopy


def retrieve_news(scenario):
    records = scenario.get("news_sources", [])
    if not isinstance(records, list):
        raise ValueError("news_sources must be a list of controlled source records")
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("source_id"), str):
            raise ValueError("Each source needs a source_id")
        if record.get("verdict") not in ("supports", "refutes", "unknown"):
            raise ValueError("Source verdict must be supports, refutes, or unknown")
    return deepcopy(records)


def cross_check_sources(records):
    supporting, refuting = set(), set()
    for source in records:
        # The group is fixture metadata describing provenance, not article text.
        group = source.get("independence_group")
        if source.get("trusted") is not True or not isinstance(group, str) or not group.strip():
            continue
        if source["verdict"] == "supports":
            supporting.add(group)
        elif source["verdict"] == "refutes":
            refuting.add(group)
    return {"independent_supporting_sources": len(supporting),
            "independent_refuting_sources": len(refuting),
            "conflicting_evidence": bool(supporting and refuting)}


def verify_claim(scenario):
    sources = retrieve_news(scenario)
    evidence = cross_check_sources(sources)
    label = "unverified"
    if not evidence["conflicting_evidence"]:
        if evidence["independent_supporting_sources"] >= 2:
            label = "credible"
        elif evidence["independent_refuting_sources"] >= 2:
            label = "false"
    return {"news_label": label, "evidence": evidence,
            "source_ids": [s["source_id"] for s in sources],
            "retrieval_mode": "controlled_scenario_fixtures",
            "trigger_is_untrusted": True,
            "limitation": "No live news retrieval. Missing or conflicting evidence remains unverified."}


# Instrument actual tool invocations, including nested deterministic calculations.
from backend.telemetry import tracked_tool
for _name, _value in list(globals().items()):
    if callable(_value) and getattr(_value, '__module__', None) == __name__ and not _name.startswith('_') and not isinstance(_value, type):
        globals()[_name] = tracked_tool(_value)
