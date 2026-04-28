import json


def validate_json(content: str) -> bool:
    try:
        json.loads(content)
        return True
    except (json.JSONDecodeError, ValueError):
        return False
