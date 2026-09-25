"""Run the app with a deterministic stand-in for the AI model (for e2e/atoms.mjs).

Usage: WORKBENCH_DATA_DIR=<tmp> python frontend/e2e/fake_llm_server.py [port]
Extraction turns every transcript line into an atom quoting that line; the
duplicate check reports the first two new atoms as conflicting.
"""
import functools
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import app as app_module  # noqa: E402
from core import atoms  # noqa: E402


def fake_complete(system, user, schema, prefs, api_key, ollama_url):
    if "duplicates" in schema["properties"]:
        new = re.findall(r"^(N\d+) ", user, flags=re.M)
        return {"duplicates": [], "conflicts": [{"a": new[0], "b": new[1], "description": "Разные требования к сроку"}]
                if len(new) > 1 else []}
    found = []
    for idx, text in re.findall(r"^\[S(\d+)\] (?:\[[^\]]*\] )?(.+)$", user, flags=re.M):
        kind = "nfr" if "секунд" in text else "question" if "?" in text else "functional"
        found.append({"type": kind, "statement": "Система: " + text, "evidence": [{"segment": int(idx), "quote": text}]})
    return {"atoms": found}


app_module.extract_atoms = functools.partial(atoms.extract_atoms, complete=fake_complete)
app_module.settings.secret = lambda name: "fake-key"

if __name__ == "__main__":
    app_module.app.run(host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 5098, threaded=True)
