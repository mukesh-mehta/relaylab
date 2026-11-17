RULES = [
    {"name": "High-value invoices", "target": "finance-review", "mode": "all", "conditions": [
        {"path": "/type", "op": "equals", "value": "invoice.paid"},
        {"path": "/data/amount", "op": "greater_than", "value": 2000},
    ]},
    {"name": "Main branch deployments", "target": "deployment-pipeline", "mode": "all", "conditions": [
        {"path": "/type", "op": "equals", "value": "repository.push"},
        {"path": "/data/ref", "op": "equals", "value": "refs/heads/main"},
    ]},
]
