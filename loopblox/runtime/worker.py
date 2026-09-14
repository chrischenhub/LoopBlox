"""Run candidate Python inside the controller container; effects use the host pipe."""

import contextlib
import json
import sys
import traceback


class Environment:
    def __init__(self, initial, reader, writer):
        self.task = initial["task"]
        self.tools = initial["tools"]
        self.components = initial["components"]
        self._reader = reader
        self._writer = writer

    def _request(self, method, **arguments):
        self._writer.write(json.dumps({"method": method, "arguments": arguments}) + "\n")
        self._writer.flush()
        response = json.loads(self._reader.readline())
        if "error" in response:
            raise RuntimeError(response["error"])
        return response["result"]

    def component(self, name, **arguments):
        return self._request("component", name=name, **arguments)

    @property
    def history(self):
        return self._request("history")

    @property
    def remaining(self):
        return self._request("remaining")


def main():
    reader, writer = sys.stdin, sys.stdout
    initial = json.loads(reader.readline())
    environment = Environment(initial, reader, writer)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            namespace = {"__name__": "controller"}
            exec(compile(initial["source"], "controller.py", "exec"), namespace)
            result = namespace["run"](environment)
        writer.write(json.dumps({"finished": result}) + "\n")
    except BaseException:
        writer.write(json.dumps({"candidate_error": traceback.format_exc()[-16000:]}) + "\n")
    writer.flush()


if __name__ == "__main__":
    main()
