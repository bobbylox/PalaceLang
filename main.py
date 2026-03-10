#!/usr/bin/env python3
"""
Palace Language — Interactive REPL

Type commands as if speaking them aloud.  The IDE parses each utterance into
the AST; 'run' commands are handed to the interpreter and the result is printed.

Type 'quit' to leave.
"""

import sys
import os

# allow running from the repo root
sys.path.insert(0, os.path.dirname(__file__))

from IDE.parser import IDE
from Interpreter.interpreter import Interpreter


def respond(msg: str):
    print(f"IDE: {msg}")


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

        if not result["ok"]:
            respond(result.get("error", "unrecognized"))
            continue

        action = result["action"]
        op = action.get("op", "")

        # ---- run a device ------------------------------------------------
        if op == "run":
            palace = action.get("palace")
            room   = action.get("room") or "lobby"
            device = action["device"]
            value  = action.get("input")

            if palace is None:
                respond("not inside a palace")
                continue

            palaces = ide.ast.get("palaces", {})
            r = palaces.get(palace, {}).get("rooms", {}).get(room, {})
            if device not in r.get("devices", {}):
                respond(f"no device {device}")
                continue

            dev_meta = r["devices"][device]
            if (value is None
                    and dev_meta.get("input", {}).get("type", "untyped")
                    != "untyped"):
                input_type = dev_meta["input"].get("type", "unknown")
                respond(f"{device} requires an input of type {input_type}")
                continue

            try:
                out = interp.run_device(palace, room, device, value)
                respond(str(out))
            except Exception as e:
                respond(f"error — {e}")
            continue

        # ---- query responses ---------------------------------------------
        if op == "whereami":
            parts = []
            if action.get("device"):
                parts.append(f"device {action['device']}")
            if action.get("room"):
                parts.append(f"room {action['room']}")
            if action.get("palace"):
                parts.append(f"palace {action['palace']}")
            respond(", ".join(parts) if parts else "outside")
            continue

        if op == "query.length":
            respond(str(action["length"]))
            continue

        if op == "query.step_length":
            respond(str(action["length"]))
            continue

        if op == "query.link":
            if action.get("value_of"):
                respond(str(action["value"]))
            else:
                respond(action["description"])
            continue

        if op == "set.comment":
            respond("noted")
            continue

        # ---- default: anything else is "yes" -----------------------------
        respond("yes")


if __name__ == "__main__":
    main()
