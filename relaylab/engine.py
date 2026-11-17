"""Deterministic routing simulation. No evaluation of code or outbound I/O."""
import json
import math
import re

MISSING = object()
OPERATORS = ("equals", "contains", "exists", "greater_than")


def strict_json(raw):
    def reject(value):
        raise ValueError(f"Non-finite JSON number: {value}")

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            reject(value)
        return number

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON object key.")
            result[key] = value
        return result

    return json.loads(raw, parse_constant=reject, parse_float=finite_float, object_pairs_hook=unique_keys)


def text(value, field, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{field} must contain 1–{limit} characters.")
    return value.strip()


def validate_rule(data):
    if not isinstance(data, dict) or data.keys() - {"name", "target", "mode", "conditions", "enabled"}:
        raise ValueError("Send a rule object with name, target, mode, conditions, and enabled fields only.")
    result = {key: text(data.get(key), key, limit) for key, limit in (("name", 80), ("target", 80))}
    result["mode"] = data.get("mode", "all")
    if result["mode"] not in ("all", "any"):
        raise ValueError("mode must be all or any.")
    result["enabled"] = data.get("enabled", True)
    if type(result["enabled"]) is not bool:
        raise ValueError("enabled must be a boolean.")
    conditions = data.get("conditions")
    if not isinstance(conditions, list) or not 1 <= len(conditions) <= 8:
        raise ValueError("Use between 1 and 8 conditions.")
    for condition in conditions:
        if not isinstance(condition, dict) or set(condition) != {"path", "op", "value"}:
            raise ValueError("Each condition needs exactly path, op, and value.")
        pointer = condition["path"]
        if (not isinstance(pointer, str) or len(pointer) > 300
                or (pointer and not pointer.startswith("/")) or re.search(r"~(?![01])", pointer)):
            raise ValueError("path must be a JSON Pointer, such as /data/amount; escape ~ as ~0 and / as ~1.")
        op, value = condition["op"], condition["value"]
        if op not in OPERATORS:
            raise ValueError(f"op must be one of: {', '.join(OPERATORS)}.")
        if isinstance(value, (dict, list)) or (isinstance(value, str) and len(value) > 1000):
            raise ValueError("Condition values must be JSON scalars; strings are limited to 1,000 characters.")
        if type(value) in (int, float) and (isinstance(value, float) and not math.isfinite(value)):
            raise ValueError("Condition numbers must be finite.")
        if op == "exists" and type(value) is not bool:
            raise ValueError("exists requires a boolean value.")
        if op == "contains" and not isinstance(value, str):
            raise ValueError("contains requires a string value.")
        if op == "greater_than" and type(value) not in (int, float):
            raise ValueError("greater_than requires a numeric value.")
    result["conditions"] = conditions
    return result


def resolve(document, pointer):
    """Resolve RFC 6901 pointers, distinguishing an absent field from JSON null."""
    current = document
    if pointer == "":
        return current
    for encoded in pointer[1:].split("/"):
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                return MISSING
            current = current[token]
        elif isinstance(current, list) and re.fullmatch(r"0|[1-9][0-9]*", token):
            # Bound index parsing independently of Python's integer-string limit.
            if len(token) > 10 or int(token) >= len(current):
                return MISSING
            current = current[int(token)]
        else:
            return MISSING
    return current


def evaluate_condition(document, condition):
    actual = resolve(document, condition["path"])
    op, expected = condition["op"], condition["value"]
    if op == "exists":
        matched = (actual is not MISSING) == expected
    elif actual is MISSING:
        matched = False
    elif op == "equals":
        numbers = type(actual) in (int, float) and type(expected) in (int, float)
        matched = (numbers or type(actual) is type(expected)) and actual == expected
    elif op == "contains":
        matched = isinstance(actual, str) and expected in actual
    else:
        matched = type(actual) in (int, float) and actual > expected
    return {**condition, "matched": bool(matched), "present": actual is not MISSING}


def simulate(document, rules):
    decisions, targets = [], []
    for rule in rules:
        if not rule["enabled"]:
            continue
        checks = [evaluate_condition(document, condition) for condition in rule["conditions"]]
        outcomes = [check["matched"] for check in checks]
        matched = all(outcomes) if rule["mode"] == "all" else any(outcomes)
        decisions.append({"rule_id": rule["id"], "revision": rule["revision"], "name": rule["name"],
                          "target": rule["target"], "mode": rule["mode"], "matched": matched, "checks": checks})
        if matched and rule["target"] not in targets:
            targets.append(rule["target"])
    return {"engine_version": 1, "targets": targets, "decisions": decisions, "delivery_performed": False}
