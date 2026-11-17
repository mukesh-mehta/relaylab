import pytest

from relaylab.engine import MISSING, evaluate_condition, resolve, simulate, validate_rule


@pytest.mark.parametrize("pointer,expected", [
    ("", {"a/b": {"~name": [None, 42]}, "": False}),
    ("/a~1b/~0name/1", 42), ("/a~1b/~0name/0", None), ("/", False),
    ("/absent", MISSING), ("/a~1b/~0name/01", MISSING),
    ("/a~1b/~0name/-", MISSING), ("/a~1b/~0name/2", MISSING),
    ("/a~1b/~0name/" + "9" * 200, MISSING),
])
def test_json_pointer_resolution(pointer, expected):
    document = {"a/b": {"~name": [None, 42]}, "": False}
    actual = resolve(document, pointer)
    assert actual is MISSING if expected is MISSING else actual == expected


@pytest.mark.parametrize("document,path,op,value,expected", [
    ({"x": True}, "/x", "equals", 1, False),
    ({"x": 1}, "/x", "equals", 1.0, True),
    ({"x": "1"}, "/x", "equals", 1, False),
    ({"x": None}, "/x", "exists", True, True),
    ({}, "/x", "exists", False, True),
    ({}, "/x", "equals", None, False),
    ({"x": "hello"}, "/x", "contains", "ell", True),
    ({"x": ["hello"]}, "/x", "contains", "hello", False),
    ({"x": True}, "/x", "greater_than", 0, False),
    ({"x": 4}, "/x", "greater_than", 3, True),
    ({"x": "4"}, "/x", "greater_than", 3, False),
])
def test_typed_comparisons(document, path, op, value, expected):
    assert evaluate_condition(document, {"path": path, "op": op, "value": value})["matched"] is expected


@pytest.mark.parametrize("condition", [
    {"path": "data.id", "op": "equals", "value": 1},
    {"path": "/bad~2", "op": "equals", "value": 1},
    {"path": "/x", "op": "eval", "value": "malicious()"},
    {"path": "/x", "op": "exists", "value": 1},
    {"path": "/x", "op": "contains", "value": True},
    {"path": "/x", "op": "greater_than", "value": False},
    {"path": "/x", "op": "equals", "value": {}},
    {"path": "/x", "op": "equals", "value": float("inf")},
    {"path": "/x", "op": "equals", "value": 1, "extra": True},
])
def test_unsupported_rules_are_rejected(condition):
    with pytest.raises(ValueError):
        validate_rule({"name": "Rule", "target": "label", "conditions": [condition]})


def test_all_any_disabled_and_target_deduplication():
    conditions = [{"path": "/x", "op": "equals", "value": 1}, {"path": "/y", "op": "exists", "value": True}]
    rules = [dict(id=i, revision=1, name=f"Rule {i}", target="same-target", mode=mode, enabled=enabled, conditions=conditions)
             for i, mode, enabled in [(1, "all", True), (2, "any", True), (3, "any", True), (4, "any", False)]]
    run = simulate({"x": 1}, rules)
    assert run["targets"] == ["same-target"]
    assert [decision["matched"] for decision in run["decisions"]] == [False, True, True]
    assert run["delivery_performed"] is False
