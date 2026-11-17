"""Send synthetic requests to a running local RelayLab, using only stdlib."""
import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

SAMPLES = [
    {"type": "invoice.paid", "data": {"amount": 4200, "currency": "USD", "invoice_id": "inv_demo_1042"}},
    {"type": "repository.push", "data": {"repository": "demo/service-api", "ref": "refs/heads/main"}},
    {"type": "invoice.paid", "data": {"amount": 350, "currency": "USD", "invoice_id": "inv_demo_1043"}},
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5050")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1") or parsed.path or parsed.query or parsed.fragment or parsed.username:
        parser.error("Use a local HTTP origin, such as http://127.0.0.1:5050")
    try:
        with urlopen(base + "/api/inboxes", timeout=5) as response:
            inboxes = json.load(response)["inboxes"]
        if not inboxes:
            parser.error("Create an inbox in the UI or run: python -m flask --app relaylab seed")
        endpoint = base + inboxes[0]["path"]
        for sample in SAMPLES:
            request = Request(endpoint, data=json.dumps(sample).encode(), headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(request, timeout=5) as response:
                print(f"{response.status}: {sample['type']} -> event {json.load(response)['event_id']}")
    except (HTTPError, URLError) as error:
        print(f"Unable to send sample traffic: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
