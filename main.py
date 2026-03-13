#!/usr/bin/env python3
"""
Palace Language — Interactive REPL

Type commands as if speaking them aloud.  The IDE parses each utterance into
the AST; 'run' commands are handed to the interpreter and the result is printed.

Type 'quit' to leave.
"""

import json
import sys
import os

# allow running from the repo root
sys.path.insert(0, os.path.dirname(__file__))

from IDE.parser import IDE
from Interpreter.interpreter import Interpreter


def respond(msg: str):
    print(f"IDE: {msg}")


def save_state(ast: dict):
    palaces = ast.get("palaces", {})
    if not palaces:
        return
    palace_name = next(iter(palaces))
    filename = palace_name.replace(" ", "_") + ".json"
    with open(filename, "w") as f:
        json.dump(ast, f, indent=2)


def main():
    ide = IDE()
    interp = Interpreter(ide.ast)   # interpreter shares the same AST object

    print("Palace Language IDE  (type 'quit' to exit)\n")

    while True:
        try:
            raw = input("YOU: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            continue
        if raw.lower() == "quit":
            break

        result = ide.process(raw)
        save_state(ide.ast)

        if not result["ok"]:
            respond(result.get("error", "unrecognized"))
            continue

        action = result["action"]

        # ---- load palace from disk (needs filesystem access) -------------
        if action.get("operator") == "load.palace":
            name = action["name"]
            filename = name.replace(" ", "_") + ".json"
            if not os.path.exists(filename):
                respond(f"no palace {name!r} and no file {filename!r}")
                continue
            with open(filename) as f:
                data = json.load(f)
            palace_data = data.get("palaces", {}).get(name)
            if palace_data is None:
                respond(f"{filename!r} does not contain palace {name!r}")
                continue
            ide.load_palace(name, palace_data)
            save_state(ide.ast)
            respond("yes")
            continue

        respond(interp.execute(action))


if __name__ == "__main__":
    main()
