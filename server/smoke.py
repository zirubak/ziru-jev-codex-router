"""Small end-to-end check through the parent router; never print credentials."""
import argparse
import http.client
import json
from pathlib import Path

from healthcheck import healthy
from local_runtime import STATE
from routing_policy import POLICY_VERSION


def main(route: str = "jev/auto") -> None:
    targets = {"jev/sol": "gpt-6.1-sol", "jev/astra": "gpt-6-astra"}
    if route not in ("jev/auto", "jev/manual", *targets):
        raise ValueError("unsupported smoke route")
    if not healthy():
        raise RuntimeError("local health check failed")
    health = http.client.HTTPConnection("127.0.0.1", 4319, timeout=5)
    try:
        health.request("GET", "/health")
        if json.loads(health.getresponse().read()).get("policy_version") != POLICY_VERSION:
            raise RuntimeError("running policy differs from checkout; reload required")
    finally:
        health.close()
    secret = (Path(STATE) / "caller-secret").read_text().strip()
    connection = http.client.HTTPConnection("127.0.0.1", 4202, timeout=120)
    result = {"policy": POLICY_VERSION, "route": route, "model": None, "status": None}
    created_model = None
    try:
        # Exercise Desktop's native replay path so a stale automatic quota
        # deadline cannot divert installation verification to external fallback.
        body = {"model": route, "input": [
            {"role": "user", "content": [{"type": "input_text", "text": "Reply only OK."}]}
        ], "stream": True, "reasoning": {"context": "all_turns"},
            "parallel_tool_calls": False}
        connection.request("POST", f"/_codex-router/{secret}/v1/responses",
                           json.dumps(body), {"Content-Type": "application/json",
                                              "x-openai-internal-codex-responses-lite": "true"})
        response = connection.getresponse()
        result["http"] = response.status
        if response.status != 200:
            raise RuntimeError(f"parent router returned HTTP {response.status}")
        for line in response:
            if not line.startswith(b"data: "):
                continue
            try:
                event = json.loads(line[6:])
            except ValueError:
                continue
            if event.get("type") == "response.created":
                created_model = (event.get("response") or {}).get("model")
            if event.get("type") == "response.completed":
                result["model"] = (event.get("response") or {}).get("model")
                result["status"] = (event.get("response") or {}).get("status")
        if result["status"] != "completed":
            raise RuntimeError("no successful terminal response")
        if route in targets and (
            created_model != targets[route] or result["model"] != targets[route]
        ):
            raise RuntimeError("native response did not confirm the selected model")
        print(json.dumps(result))
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", choices=("auto", "manual", "sol", "astra"), default="auto")
    arguments = parser.parse_args()
    try:
        main(f"jev/{arguments.route}")
    except Exception as error:
        # Transport exceptions can carry request URLs: expose only their class.
        print(json.dumps({"ok": False, "error_type": type(error).__name__}))
        raise SystemExit(1)
