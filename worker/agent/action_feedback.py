"""Name the required action fields a model reply left out, without echoing the reply.

ActionInputError carries only a code (worker/schemas.py). For invalid_fields the agent
tells the model which required field of the chosen action is missing, and records the
same field names in attempt.end_detail. Values and reply text are never used.
"""
import json
from typing import get_args

from worker.schemas import (BackAction, ClickAction, DoneAction, FailAction, ScrollAction,
                            SelectAction, TypeAction, WaitAction)

ACTION_MODELS = (ClickAction, TypeAction, SelectAction, ScrollAction,
                 BackAction, WaitAction, DoneAction, FailAction)

# action name -> required field names, in model field order (read from worker/schemas.py).
REQUIRED_FIELDS = {
    get_args(model.model_fields['action'].annotation)[0]:
        tuple(name for name, field in model.model_fields.items() if field.is_required())
    for model in ACTION_MODELS
}
# action name -> every field the action accepts (required and optional, e.g. type.submit #75).
ALLOWED_FIELDS = {
    get_args(model.model_fields['action'].annotation)[0]: frozenset(model.model_fields)
    for model in ACTION_MODELS
}


def missing_fields(payload):
    """Return (action name, missing required field names); (None, ()) if not determinable."""
    try:
        raw = json.loads(payload)
    except (TypeError, ValueError, RecursionError):
        return None, ()
    if not isinstance(raw, dict):
        return None, ()
    name = raw.get('action')
    if not isinstance(name, str) or name not in REQUIRED_FIELDS:
        return None, ()
    return name, tuple(field for field in REQUIRED_FIELDS[name] if raw.get(field) is None)


def unexpected_fields(payload):
    """Field names (never values) the chosen action does not accept, e.g. submit on click (#75)."""
    try:
        raw = json.loads(payload)
    except (TypeError, ValueError, RecursionError):
        return ()
    if not isinstance(raw, dict):
        return ()
    name = raw.get('action')
    if not isinstance(name, str) or name not in ALLOWED_FIELDS:
        return ()
    return tuple(sorted(str(key) for key in raw if key not in ALLOWED_FIELDS[name]))


def retry_message(code, name, missing, unexpected=()):
    if name and missing:
        return (f'The previous action was invalid ({code}): missing {", ".join(missing)} for {name}. '
                'Include every required field for the chosen action.')
    if name and unexpected:
        return (f'The previous action was invalid ({code}): {", ".join(unexpected)} is not used by {name}. '
                'Set fields of other actions to null (submit is only for type).')
    return (f'The previous action was invalid ({code}). '
            'Choose a valid action with every required field.')


def failure_code(code, missing):
    """ActionInputError code for the final failure, e.g. invalid_fields:target."""
    return f'{code}:{",".join(missing)}' if missing else code
