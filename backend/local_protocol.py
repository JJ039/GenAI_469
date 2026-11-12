"""Ollama response schemas derived from the agent's trusted protocol state."""
import json


def object_schema(properties):
    return {'type': 'object', 'properties': properties,
            'required': list(properties), 'additionalProperties': False}


def response_schema(prompt):
    def has_state(marker):
        return prompt.startswith(marker + '\n') or '\n' + marker + '\n' in prompt

    if has_state('COMPLIANCE_REVIEW_STATE:'):
        state = json.JSONDecoder().raw_decode(prompt.split('COMPLIANCE_REVIEW_STATE:', 1)[1].lstrip())[0]
        evidence = [item['evidence_id'] for group in state['evidence_by_authority'].values() for item in group]
        retrieve = object_schema({'type': {'const': 'retrieve'}, 'query': {'type': 'string', 'minLength': 1}})
        if not evidence and state.get('retrieval_calls_remaining', 0) and state.get('turns_remaining', 0):
            return retrieve
        final = object_schema({
            'type': {'const': 'final'},
            'finding': {'type': 'string', 'enum': ['compliant', 'non_compliant', 'undetermined'] if evidence else ['undetermined']},
            'rationale': {'type': 'string'},
            'citations': {'type': 'array', 'items': {'type': 'string', 'enum': evidence}} if evidence else {'const': []},
            'missing_facts': {'type': 'array', 'items': {'type': 'string'}},
        })
        if state.get('retrieval_calls_remaining', 0) and state.get('turns_remaining', 0):
            return {'anyOf': [final, retrieve]}
        return final
    marker = next((name for name in ('SPECIALIST_AGENT_STATE:', 'FINANCIAL_REACT_STATE:')
                   if has_state(name)), None)
    if marker is None:
        return 'json'
    state = json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1].lstrip())[0]
    observations = [row['observation'] for row in state['history']
                    if row.get('observation', {}).get('ok')]
    ids = [row['id'] for row in observations]
    seen = {row['tool'] for row in observations}
    financial = marker == 'FINANCIAL_REACT_STATE:'
    required = ['build_financial_report'] if financial else state['context']['required_tools']
    missing = [name for name in required if name not in seen]
    tools = [item['name'] for item in state['tools']]
    # Complete mandatory evidence gathering before allowing a final response.
    if missing:
        tools = missing
    else:
        tools = [item['name'] for item in state['tools']
                 if item['name'] not in seen or item.get('arguments')]
    tool_schema = object_schema({
        'type': {'const': 'tool_call'}, 'tool': {'type': 'string', 'enum': tools},
        'arguments': {'type': 'object'},
    })
    if financial:
        final_schema = object_schema({
            'type': {'const': 'final'},
            'recommendation': object_schema({
                'recommendation': {'type': 'string', 'enum': ['hold', 'borrow_interbank', 'draw_central_bank_facility']},
                'amount': {'type': 'number', 'minimum': 0},
                'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
                'rationale': {'type': 'string'},
            }),
            'claims': {'type': 'array', 'minItems': 1, 'items': object_schema({
                'metric': {'type': 'string'}, 'value': {'type': 'number'},
                'unit': {'type': 'string', 'enum': ['amount', 'thousand', 'million', 'billion', 'ratio', 'percent', 'days']},
                'observation_id': {'type': 'string', 'enum': ids},
            })},
        })
    else:
        required_ids = [row['id'] for row in observations if row['tool'] in required]
        final_schema = object_schema({
            'type': {'const': 'final'}, 'summary': {'type': 'string'},
            'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
            'observation_ids': {'type': 'array', 'const': required_ids},
        })
    if missing:
        return tool_schema
    if not tools or state.get('tool_calls_remaining', 0) == 0 or state.get('steps_remaining', 0) == 0:
        return final_schema
    return {'anyOf': [final_schema, tool_schema]}
