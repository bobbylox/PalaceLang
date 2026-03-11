#!/usr/bin/env python3
"""
Palace Language test suite.

Covers:
  1. The canonical fibonacci example session from the README.
  2. Creation keywords (device / box / room / chain as 'new').
  3. Box scoping (device-local vs room-level).
  4. Wing navigation.
  5. Typed boxes.

Run with:  python3 tests.py
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from IDE.parser import IDE
from Interpreter.interpreter import Interpreter


# ---------------------------------------------------------------------------
# Shared REPL helper
# ---------------------------------------------------------------------------

def make_repl():
    """Return (ide, interp, repl_fn) bound together."""
    ide = IDE()
    interp = Interpreter(ide.ast)

    def repl(utterance: str) -> str:
        result = ide.process(utterance)
        if not result["ok"]:
            return result.get("error", "unrecognized")
        action = result["action"]
        op = action.get("op", "")

        if op == "run":
            palace = action.get("palace")
            room   = action.get("room") or "lobby"
            device = action["device"]
            value  = action.get("input")
            if palace is None:
                return "not inside a palace"
            palace_obj = ide.ast.get("palaces", {}).get(palace, {})
            r = palace_obj.get("rooms", {}).get(room)
            if r is None:
                for wing_obj in palace_obj.get("wings", {}).values():
                    r = wing_obj.get("rooms", {}).get(room)
                    if r is not None:
                        break
            r = r or {}
            contents = r.get("contents", {})
            if device not in contents or contents[device].get("type") != "device":
                return f"no device {device}"
            dev_meta = contents[device]
            input_value_type = dev_meta.get("input", {}).get("value_type")
            if value is None and input_value_type is not None:
                return f"{device} requires an input of type {input_value_type}"
            try:
                return str(interp.run_device(palace, room, device, value))
            except Exception as e:
                return f"error — {e}"

        if op == "run.instance":
            palace = action.get("palace")
            room_name = action.get("room_name", "lobby")
            instance = action["instance"]
            device = action["device"]
            input_val = action.get("input")
            if palace is None:
                return "not inside a palace"
            try:
                return str(interp.run_instance_device(palace, room_name, instance, device, input_val))
            except Exception as e:
                return f"error — {e}"

        if op == "whereami":
            parts = []
            if action.get("device"): parts.append(f"device {action['device']}")
            if action.get("room"):   parts.append(f"room {action['room']}")
            if action.get("wing"):   parts.append(f"wing {action['wing']}")
            if action.get("palace"): parts.append(f"palace {action['palace']}")
            return ", ".join(parts) if parts else "outside"

        if op == "query.length":       return str(action["length"])
        if op == "query.step_length":  return str(action["length"])
        if op == "query.link":
            return (str(action["value"]) if action.get("value_of")
                    else action["description"])
        if op == "look.around":        return action["description"]
        if op == "set.comment":        return "noted"
        return "yes"

    return ide, interp, repl


# ---------------------------------------------------------------------------
# 1. Canonical fibonacci session
# ---------------------------------------------------------------------------

class TestFibonacciSession(unittest.TestCase):
    """Replays the example session from the README.

    Notes on deviations from the README text:
    - Palace name normalised to 'fibonacci' (README has a double-b typo that
      makes the creation name differ from the run-command name).
    - 'where am I?' reports 'room lobby' because the session enters lobby,
      not helper (helper is only created, not entered).
    """

    STEPS = [
        # (utterance, expected_response)
        ("palace fibonacci",                                           "yes"),
        ("enter it",                                                   "yes"),
        ("room helper",                                                "yes"),
        ("chain sequence",                                             "chain must be in a room"),
        ("enter lobby",                                                "yes"),
        ("chain sequence over",                                        "yes"),
        ("append link to sequence",                                    "yes"),
        ("set link value to 0",                                        "yes"),
        ("set sequence link 2 to 1",                                   "yes"),
        ("set link value to 1",                                        "yes"),
        ("append 1 to sequence",                                       "yes"),
        ("append false to sequence",                                   "cannot append boolean to chain of type number"),
        ("length of sequence?",                                        "3"),
        ("enter device adder over",                                "yes"),
        ("set comment to this is a device for calculating fibonacci numbers recursively",
                                                                       "noted"),
        ("where am I?",                                                "device adder, room lobby, palace fibonacci"),
        ("what is the value of sequence link 2?",                      "1"),
        ("what is sequence link 1?",
         'link 1 is a link with value 0 and next link "link 2"'),
        ("set input name to place stop",                               "yes"),
        ("set input type to integer",                                  "yes"),
        ("enter process",                                              "yes"),
        ("set step 1 to if place is less than length of sequence",     "yes"),
        ("set step 2 to return sequence link input",                   "yes"),
        ("what is step length?",                                       "2"),
        ("set step 3 to else",                                         "yes"),
        ("then set box a to sequence link input minus 2",          "yes"),
        ("then set box b to sequence link input minus 1",          "yes"),
        ("then sequence link input is a plus b",                       "yes"),
        ("then return sequence input",                                 "yes"),
        ("run adder",                                                  "adder requires an input of type integer"),
        ("run adder on 5",                                             "3"),
        ("exit",                                                       "yes"),
        ("run adder on 8",                                             "13"),
        ("go to helper",                                               "yes"),
        ("run adder on 9",                                             "no device adder"),
        ("run lobby's adder on 9",                                     "21"),
        ("go outside",                                                 "yes"),
        ("run fibonacci's lobby's adder on 10",                        "34"),
    ]

    def setUp(self):
        self.ide, self.interp, self.repl = make_repl()

    def test_session(self):
        for utterance, expected in self.STEPS:
            with self.subTest(utterance=utterance):
                self.assertEqual(self.repl(utterance), expected)


# ---------------------------------------------------------------------------
# 2. Creation keywords
# ---------------------------------------------------------------------------

class TestCreationKeywords(unittest.TestCase):
    """'device NAME' and 'box NAME' act as creation without entering."""

    def setUp(self):
        self.ide, self.interp, self.repl = make_repl()
        self.repl("palace test")
        self.repl("enter lobby")

    def test_device_creates_without_entering(self):
        self.assertEqual(self.repl("device adder"), "yes")
        # cursor still in room, not inside the device
        self.assertIsNone(self.ide.current["device"])
        lobby = self.ide.ast["palaces"]["test"]["rooms"]["lobby"]
        self.assertIn("adder", lobby["contents"])

    def test_enter_after_device_creation(self):
        self.repl("device adder")
        self.assertEqual(self.repl("enter adder"), "yes")
        self.assertEqual(self.ide.current["device"], "adder")

    def test_box_creates_in_room_when_not_in_device(self):
        self.assertEqual(self.repl("box counter"), "yes")
        lobby = self.ide.ast["palaces"]["test"]["rooms"]["lobby"]
        self.assertIn("counter", lobby["contents"])

    def test_box_creates_in_device_when_inside_one(self):
        self.repl("device adder")
        self.repl("enter adder")
        self.assertEqual(self.repl("box temp"), "yes")
        lobby = self.ide.ast["palaces"]["test"]["rooms"]["lobby"]
        self.assertIn("temp", lobby["contents"]["adder"]["boxes"])
        self.assertNotIn("temp", lobby["contents"])

    def test_chain_requires_room(self):
        # chain at palace level (no room entered) should error
        ide2 = IDE()
        ide2.process("palace test")
        r = ide2.process("chain foo")
        self.assertFalse(r["ok"])

    def test_room_keyword_creates_room(self):
        self.assertEqual(self.repl("room storage"), "yes")
        self.assertIn("storage",
                      self.ide.ast["palaces"]["test"]["rooms"])

    def test_device_keyword_run(self):
        """Device created with keyword is runnable."""
        self.repl("device double")
        self.repl("enter double")
        self.repl("enter process")
        self.repl("then return input")
        self.assertEqual(self.repl("run double on 7"), "7")


# ---------------------------------------------------------------------------
# 3. Box scoping
# ---------------------------------------------------------------------------

class TestBoxScoping(unittest.TestCase):
    """Room-level boxes are shared; device-level boxes are local."""

    def setUp(self):
        self.ide, self.interp, self.repl = make_repl()
        for cmd in ["palace test", "enter lobby"]:
            self.repl(cmd)

    def test_room_box_written_by_device(self):
        self.repl("box shared")  # room-level
        self.repl("device writer")
        self.repl("enter writer")
        self.repl("enter process")
        self.repl("then set box shared to 99")
        self.repl("then return shared")
        self.assertEqual(self.repl("run writer"), "99")
        lobby = self.ide.ast["palaces"]["test"]["rooms"]["lobby"]
        self.assertEqual(lobby["contents"]["shared"]["value"], 99)

    def test_device_box_does_not_leak_to_room(self):
        self.repl("device worker")
        self.repl("enter worker")
        self.repl("box local")  # device-level
        self.repl("enter process")
        self.repl("then set box local to 42")
        self.repl("then return local")
        self.assertEqual(self.repl("run worker"), "42")
        lobby = self.ide.ast["palaces"]["test"]["rooms"]["lobby"]
        self.assertNotIn("local", lobby["contents"])
        self.assertIn("local", lobby["contents"]["worker"]["boxes"])

    def test_room_box_shared_between_two_devices(self):
        self.repl("box tally")
        # device A sets it
        for cmd in ["device setter", "enter setter", "enter process",
                    "then set box tally to 77", "exit"]:
            self.repl(cmd)
        # device B reads it
        for cmd in ["device getter", "enter getter", "enter process",
                    "then return tally", "exit"]:
            self.repl(cmd)
        self.repl("run setter")
        self.assertEqual(self.repl("run getter"), "77")


# ---------------------------------------------------------------------------
# 4. Wing navigation
# ---------------------------------------------------------------------------

class TestWingNavigation(unittest.TestCase):

    def setUp(self):
        self.ide, self.interp, self.repl = make_repl()
        self.repl("palace manor")

    def test_wing_creates_in_palace(self):
        self.assertEqual(self.repl("wing east"), "yes")
        self.assertIn("east", self.ide.ast["palaces"]["manor"]["wings"])

    def test_enter_wing_sets_context(self):
        self.repl("wing east")
        self.repl("enter east")
        self.assertEqual(self.ide.current["wing"], "east")
        self.assertIsNone(self.ide.current["room"])

    def test_room_in_wing_lives_under_wing(self):
        self.repl("wing east")
        self.repl("enter east")
        self.repl("room vault")
        wings = self.ide.ast["palaces"]["manor"]["wings"]
        self.assertIn("vault", wings["east"]["rooms"])
        self.assertNotIn("vault", self.ide.ast["palaces"]["manor"]["rooms"])

    def test_whereami_includes_wing(self):
        self.repl("wing east")
        self.repl("enter east")
        self.repl("room vault")
        self.repl("enter vault")
        self.assertEqual(self.repl("where am I?"),
                         "room vault, wing east, palace manor")

    def test_go_to_finds_room_across_wings(self):
        self.repl("wing east")
        self.repl("enter east")
        self.repl("room vault")
        self.repl("go outside")
        self.repl("palace manor")
        self.assertEqual(self.repl("go to vault"), "yes")
        self.assertEqual(self.ide.current["wing"], "east")
        self.assertEqual(self.ide.current["room"], "vault")

    def test_exit_unwinds_room_then_wing(self):
        self.repl("wing east")
        self.repl("enter east")
        self.repl("room vault")
        self.repl("enter vault")
        self.repl("exit")  # exit room
        self.assertIsNone(self.ide.current["room"])
        self.assertEqual(self.ide.current["wing"], "east")
        self.repl("exit")  # exit wing
        self.assertIsNone(self.ide.current["wing"])
        self.assertEqual(self.ide.current["palace"], "manor")

    def test_device_in_wing_room_is_runnable(self):
        self.repl("wing east")
        self.repl("enter east")
        self.repl("room vault")
        self.repl("enter vault")
        self.repl("enter device triple")
        self.repl("enter process")
        self.repl("then return input")
        self.assertEqual(self.repl("run triple on 4"), "4")


# ---------------------------------------------------------------------------
# 5. Typed boxes
# ---------------------------------------------------------------------------

class TestTypedBoxes(unittest.TestCase):

    def setUp(self):
        self.ide, self.interp, self.repl = make_repl()
        for cmd in ["palace test", "enter lobby"]:
            self.repl(cmd)

    def test_named_typed_box_creation(self):
        self.assertEqual(self.repl("box score of number"), "yes")
        lobby = self.ide.ast["palaces"]["test"]["rooms"]["lobby"]
        self.assertEqual(lobby["contents"]["score"],
                         {"type": "box", "value": None, "value_type": "number"})

    def test_anonymous_typed_box_creation(self):
        self.assertEqual(self.repl("box of string"), "yes")
        lobby = self.ide.ast["palaces"]["test"]["rooms"]["lobby"]
        typed = [e for e in lobby["contents"].values()
                 if e.get("type") == "box" and e.get("value_type") == "string"]
        self.assertEqual(len(typed), 1)

    def test_set_box_of_type_creates_and_assigns(self):
        self.assertEqual(self.repl("set box of number to 42"), "yes")
        lobby = self.ide.ast["palaces"]["test"]["rooms"]["lobby"]
        values = [e["value"] for e in lobby["contents"].values()
                  if e.get("type") == "box" and e.get("value_type") == "number"]
        self.assertIn(42, values)

    def test_set_box_of_type_rejects_wrong_type(self):
        resp = self.repl("set box of number to hello")
        self.assertIn("cannot set box of type number", resp)

    def test_set_box_of_boolean_rejects_number(self):
        resp = self.repl("set box of boolean to 1")
        self.assertIn("cannot set box of type boolean", resp)

    def test_runtime_type_enforcement(self):
        """Writing a wrong type to a typed box at runtime raises an error."""
        self.repl("box score of number")
        for cmd in ["device bad", "enter bad", "enter process",
                    "then set box score to hello",
                    "then return score"]:
            self.repl(cmd)
        resp = self.repl("run bad")
        self.assertIn("cannot set box of type number", resp)

    def test_runtime_correct_type_succeeds(self):
        self.repl("box score of number")
        for cmd in ["device good", "enter good", "enter process",
                    "then set box score to 7",
                    "then return score"]:
            self.repl(cmd)
        self.assertEqual(self.repl("run good"), "7")

    def test_typed_box_in_device_scope(self):
        for cmd in ["device calc", "enter calc"]:
            self.repl(cmd)
        self.assertEqual(self.repl("box result of number"), "yes")
        lobby = self.ide.ast["palaces"]["test"]["rooms"]["lobby"]
        self.assertIn("result", lobby["contents"]["calc"]["boxes"])
        self.assertNotIn("result", lobby["contents"])

    def test_untyped_box_accepts_number(self):
        # String literals are not yet supported in the expression evaluator;
        # untyped boxes accept any value that the evaluator can produce.
        self.repl("box misc")
        for cmd in ["device setter", "enter setter", "enter process",
                    "then set box misc to 5",
                    "then return misc"]:
            self.repl(cmd)
        self.assertEqual(self.repl("run setter"), "5")


# ---------------------------------------------------------------------------
# 6. Typed creation: chain/bag/box of TYPE NAME  (multi-word names, plurals)
# ---------------------------------------------------------------------------

class TestTypedCreation(unittest.TestCase):
    """'chain/bag/box of TYPE NAME' — named typed structures, multi-word names."""

    def setUp(self):
        self.ide, self.interp, self.repl = make_repl()
        self.repl("palace test")
        self.repl("enter lobby")

    def _lobby(self):
        return self.ide.ast["palaces"]["test"]["rooms"]["lobby"]

    # --- chain of type name ---

    def test_chain_typed_single_word(self):
        self.assertEqual(self.repl("chain of number scores"), "yes")
        ch = self._lobby()["contents"]["scores"]
        self.assertEqual(ch["type"], "chain")
        self.assertEqual(ch["value_type"], "number")

    def test_chain_typed_plural(self):
        self.assertEqual(self.repl("chain of numbers scores"), "yes")
        self.assertEqual(self._lobby()["contents"]["scores"]["value_type"], "number")

    def test_chain_typed_multi_word_name(self):
        self.assertEqual(self.repl("chain of integers high scores"), "yes")
        self.assertIn("high scores", self._lobby()["contents"])
        self.assertEqual(self._lobby()["contents"]["high scores"]["value_type"], "integer")

    def test_chain_typed_rejects_wrong_append(self):
        self.repl("chain of number scores")
        self.assertIn("cannot append", self.repl("append false to scores"))

    def test_chain_typed_accepts_correct_append(self):
        self.repl("chain of number scores")
        self.assertEqual(self.repl("append 10 to scores"), "yes")

    def test_chain_untyped_still_works(self):
        self.assertEqual(self.repl("chain plain"), "yes")
        self.assertIsNone(self._lobby()["contents"]["plain"]["value_type"])

    # --- bag of type name ---

    def test_bag_typed_single_word(self):
        self.assertEqual(self.repl("bag of string vocab"), "yes")
        bg = self._lobby()["contents"]["vocab"]
        self.assertEqual(bg["type"], "bag")
        self.assertEqual(bg["value_type"], "string")

    def test_bag_typed_plural(self):
        self.assertEqual(self.repl("bag of integers tallies"), "yes")
        self.assertEqual(self._lobby()["contents"]["tallies"]["value_type"], "integer")

    def test_bag_typed_multi_word_name(self):
        self.assertEqual(self.repl("bag of integers alice poop"), "yes")
        self.assertIn("alice poop", self._lobby()["contents"])
        self.assertEqual(self._lobby()["contents"]["alice poop"]["value_type"], "integer")

    def test_bag_untyped_still_works(self):
        self.assertEqual(self.repl("bag plain"), "yes")
        self.assertIsNone(self._lobby()["contents"]["plain"]["value_type"])

    # --- box of type name ---

    def test_box_of_type_named_single_word(self):
        self.assertEqual(self.repl("box of number count"), "yes")
        bx = self._lobby()["contents"]["count"]
        self.assertEqual(bx["type"], "box")
        self.assertEqual(bx["value_type"], "number")

    def test_box_of_type_named_plural(self):
        self.assertEqual(self.repl("box of booleans flag"), "yes")
        self.assertEqual(self._lobby()["contents"]["flag"]["value_type"], "boolean")

    def test_box_of_type_named_multi_word(self):
        self.assertEqual(self.repl("box of strings fiddly dee"), "yes")
        self.assertIn("fiddly dee", self._lobby()["contents"])
        self.assertEqual(self._lobby()["contents"]["fiddly dee"]["value_type"], "string")

    def test_box_of_type_anon_still_works(self):
        self.assertEqual(self.repl("box of number"), "yes")
        typed = [e for e in self._lobby()["contents"].values()
                 if e.get("type") == "box" and e.get("value_type") == "number"]
        self.assertEqual(len(typed), 1)

    def test_box_named_of_type_still_works(self):
        self.assertEqual(self.repl("box score of number"), "yes")
        self.assertIn("score", self._lobby()["contents"])

    def test_unknown_type_rejected(self):
        r = self.repl("chain of widgets foo")
        self.assertIn("unknown type", r)
        r = self.repl("bag of widgets foo")
        self.assertIn("unknown type", r)
        r = self.repl("box of widgets foo")
        self.assertIn("unknown type", r)


# ---------------------------------------------------------------------------
# 7. Possessive set: "set OWNER's PROPERTY to VALUE"
# ---------------------------------------------------------------------------

class TestPossessiveSet(unittest.TestCase):
    """set OWNER's PROPERTY to VALUE accesses named items in the current context."""

    def setUp(self):
        self.ide, self.interp, self.repl = make_repl()
        self.repl("palace test")
        self.repl("enter lobby")
        self.repl("device calc")
        self.repl("enter calc")

    def _device(self):
        return self.ide.ast["palaces"]["test"]["rooms"]["lobby"]["contents"]["calc"]

    def _lobby(self):
        return self.ide.ast["palaces"]["test"]["rooms"]["lobby"]

    # --- device input ---

    def test_set_input_value_type(self):
        self.assertEqual(self.repl("set input's value type to number over"), "yes")
        self.assertEqual(self._device()["input"]["value_type"], "number")

    def test_set_input_value_type_plural(self):
        self.assertEqual(self.repl("set input's value type to integers"), "yes")
        self.assertEqual(self._device()["input"]["value_type"], "integer")

    def test_set_input_name(self):
        self.assertEqual(self.repl("set input's name to amount over"), "yes")
        self.assertEqual(self._device()["input"]["name"], "amount")

    # --- device-local box ---

    def test_set_device_box_value_type(self):
        self.repl("box result")
        self.assertEqual(self.repl("set result's value type to integer"), "yes")
        self.assertEqual(self._device()["boxes"]["result"]["value_type"], "integer")

    def test_set_device_box_value(self):
        self.repl("box score")
        self.assertEqual(self.repl("set score's value to 42"), "yes")
        self.assertEqual(self._device()["boxes"]["score"]["value"], 42)

    # --- room-level contents (accessed from inside a device) ---

    def test_set_room_box_value_type_from_inside_device(self):
        self.repl("exit")
        self.repl("box tally")
        self.repl("enter calc")
        self.assertEqual(self.repl("set tally's value type to number"), "yes")
        self.assertEqual(self._lobby()["contents"]["tally"]["value_type"], "number")

    def test_set_room_chain_value_type_from_inside_device(self):
        self.repl("exit")
        self.repl("chain log")
        self.repl("enter calc")
        self.assertEqual(self.repl("set log's value type to integer"), "yes")
        self.assertEqual(self._lobby()["contents"]["log"]["value_type"], "integer")

    def test_set_room_bag_value_type_from_inside_device(self):
        self.repl("exit")
        self.repl("bag store")
        self.repl("enter calc")
        self.assertEqual(self.repl("set store's value type to string"), "yes")
        self.assertEqual(self._lobby()["contents"]["store"]["value_type"], "string")

    # --- errors ---

    def test_unknown_owner_errors(self):
        r = self.repl("set ghost's value to 5")
        self.assertIn("cannot find", r)

    def test_unknown_property_errors(self):
        r = self.repl("set input's flavor to sweet")
        self.assertIn("unknown property", r)

    # --- chain-link possessive not broken ---

    def test_chain_link_possessive_still_works(self):
        self.repl("exit")
        self.repl("chain sequence")
        self.assertEqual(self.repl("set sequence's link 1 to 0"), "yes")
        self.assertEqual(
            self._lobby()["contents"]["sequence"]["links"][0]["value"], 0)

    # --- non-possessive set with multi-word values ---

    def test_set_input_name_multi_word(self):
        self.assertEqual(self.repl("set input name to mister gooby stop"), "yes")
        self.assertEqual(self._device()["input"]["name"], "mister gooby")

    def test_set_input_name_multi_word_over(self):
        # 'over' is the command-end marker, stripped at preprocess level
        self.assertEqual(self.repl("set input name to mister gooby over"), "yes")
        self.assertEqual(self._device()["input"]["name"], "mister gooby")

    def test_set_input_type_normalizes_plural(self):
        self.assertEqual(self.repl("set input type to integers"), "yes")
        self.assertEqual(self._device()["input"]["value_type"], "integer")

    def test_set_comment_multi_word(self):
        self.assertEqual(
            self.repl("set comment to adds two numbers together over"), "noted")
        self.assertEqual(
            self._device()["comment"], "adds two numbers together")


# ---------------------------------------------------------------------------
# 7b. Set-box sugar: "set NAME to VALUE" and "set box NAME (stop) to VALUE"
# ---------------------------------------------------------------------------

class TestSetBoxSugar(unittest.TestCase):
    """'set coin to true' and 'set box dice stop to 8' are sugar for the possessive form."""

    def setUp(self):
        self.ide, self.interp, self.repl = make_repl()
        self.repl("palace test")
        self.repl("enter lobby")

    def _lobby(self):
        return self.ide.ast["palaces"]["test"]["rooms"]["lobby"]

    # --- set NAME to VALUE (room-level box) ---

    def test_set_name_to_value_bool(self):
        self.repl("box coin")
        self.assertEqual(self.repl("set coin to true"), "yes")
        self.assertEqual(self._lobby()["contents"]["coin"]["value"], True)

    def test_set_name_to_value_integer(self):
        self.repl("box of integers score stop")
        self.assertEqual(self.repl("set score to 42"), "yes")
        self.assertEqual(self._lobby()["contents"]["score"]["value"], 42)

    def test_set_name_to_value_string(self):
        self.repl("box of strings label stop")
        self.assertEqual(self.repl("set label to hello stop"), "yes")
        self.assertEqual(self._lobby()["contents"]["label"]["value"], "hello")

    def test_set_name_to_value_device_box(self):
        self.repl("device calc")
        self.repl("enter calc")
        self.repl("box result")
        self.assertEqual(self.repl("set result to 7"), "yes")
        contents = self.ide.ast["palaces"]["test"]["rooms"]["lobby"]["contents"]
        self.assertEqual(contents["calc"]["boxes"]["result"]["value"], 7)

    def test_set_name_errors_if_not_box(self):
        self.repl("chain log")
        r = self.repl("set log to 5")
        self.assertIn("not a box", r)

    def test_set_name_errors_if_not_found(self):
        r = self.repl("set ghost to 5")
        self.assertIn("cannot find", r)

    # --- set box NAME (stop) to VALUE ---

    def test_set_box_name_to_value(self):
        self.repl("box dice")
        self.assertEqual(self.repl("set box dice to 8"), "yes")
        self.assertEqual(self._lobby()["contents"]["dice"]["value"], 8)

    def test_set_box_name_stop_to_value(self):
        self.repl("box of integers dice stop")
        self.assertEqual(self.repl("set box dice stop to 8"), "yes")
        self.assertEqual(self._lobby()["contents"]["dice"]["value"], 8)

    def test_set_box_multi_word_name(self):
        self.repl("box fiddly dee stop")
        self.assertEqual(self.repl("set box fiddly dee stop to 99"), "yes")
        self.assertEqual(self._lobby()["contents"]["fiddly dee"]["value"], 99)

    def test_set_box_name_errors_if_not_box(self):
        self.repl("chain sequence")
        r = self.repl("set box sequence to 0")
        self.assertIn("not a box", r)

    def test_set_box_name_errors_if_not_found(self):
        r = self.repl("set box phantom to 1")
        self.assertIn("cannot find", r)

    # --- set box of TYPE to VALUE still works (not broken by new pattern) ---

    def test_set_box_of_type_unaffected(self):
        # _type_of_value maps int/float → "number", so use "number" type here
        self.assertEqual(self.repl("set box of number to 5"), "yes")
        anon = [v for v in self._lobby()["contents"].values()
                if v.get("type") == "box" and v.get("value_type") == "number"]
        self.assertEqual(len(anon), 1)
        self.assertEqual(anon[0]["value"], 5)


# ---------------------------------------------------------------------------
# 8. User-defined types
# ---------------------------------------------------------------------------

class TestUserTypes(unittest.TestCase):
    """User-defined types with fields and methods."""

    def setUp(self):
        self.ide, self.interp, self.repl = make_repl()
        self.repl("palace mypalace")
        self.repl("enter lobby")

    def _lobby(self):
        return self.ide.ast["palaces"]["mypalace"]["rooms"]["lobby"]

    def _type(self, name):
        return self.ide.ast["palaces"]["mypalace"]["types"][name]

    def _setup_circle(self):
        for cmd in [
            "type circle",
            "enter circle",
            "box radius",
            "enter device area",
            "step 1 return 3.14 times radius times radius",
            "set pattern to area of name",
            "exit",
            "exit",
        ]:
            self.repl(cmd)

    def test_type_creates_type_def(self):
        self.assertEqual(self.repl("type circle"), "yes")
        self.assertIn("circle", self.ide.ast["palaces"]["mypalace"]["types"])
        self.assertEqual(self._type("circle")["parent"], "bag")

    def test_enter_type_sets_context(self):
        self.repl("type circle")
        self.repl("enter circle")
        self.assertEqual(self.ide.current["type_def"], "circle")
        self.assertIsNone(self.ide.current["device"])

    def test_box_in_type_creates_field(self):
        self.repl("type circle")
        self.repl("enter circle")
        self.repl("box radius")
        self.assertIn("radius", self._type("circle")["fields"])
        # field should NOT appear in room
        self.assertNotIn("radius", self._lobby()["contents"])

    def test_enter_device_in_type(self):
        self.repl("type circle")
        self.repl("enter circle")
        self.repl("enter device area")
        self.assertEqual(self.ide.current["device"], "area")
        self.assertIn("area", self._type("circle")["devices"])

    def test_step_shorthand_adds_to_process(self):
        self.repl("type circle")
        self.repl("enter circle")
        self.repl("enter device area")
        self.repl("step 1 return 3.14 times radius times radius")
        process = self._type("circle")["devices"]["area"]["process"]
        self.assertEqual(process[0], "return 3.14 times radius times radius")

    def test_set_pattern(self):
        self.repl("type circle")
        self.repl("enter circle")
        self.repl("enter device area")
        self.repl("set pattern to area of name")
        self.assertEqual(self._type("circle")["devices"]["area"]["pattern"], "area of name")

    def test_exit_device_back_to_type(self):
        self.repl("type circle")
        self.repl("enter circle")
        self.repl("enter device area")
        self.repl("exit")
        self.assertIsNone(self.ide.current["device"])
        self.assertEqual(self.ide.current["type_def"], "circle")

    def test_exit_type_back_to_room(self):
        self.repl("type circle")
        self.repl("enter circle")
        self.repl("exit")
        self.assertIsNone(self.ide.current["type_def"])
        self.assertEqual(self.ide.current["room"], "lobby")

    def test_instantiate(self):
        self._setup_circle()
        self.assertEqual(self.repl("circle doofus"), "yes")
        self.assertIn("doofus", self._lobby()["contents"])
        self.assertEqual(self._lobby()["contents"]["doofus"]["type"], "circle")

    def test_instantiate_copies_fields(self):
        self._setup_circle()
        self.repl("circle doofus")
        self.assertIn("radius", self._lobby()["contents"]["doofus"]["fields"])

    def test_set_instance_field(self):
        self._setup_circle()
        self.repl("circle doofus")
        self.assertEqual(self.repl("set doofus radius to 3"), "yes")
        self.assertEqual(
            self._lobby()["contents"]["doofus"]["fields"]["radius"]["value"], 3)

    def test_run_instance_device(self):
        self._setup_circle()
        self.repl("circle doofus")
        self.repl("set doofus radius to 3")
        result = self.repl("run doofus' area")
        self.assertAlmostEqual(float(result), 28.26, places=1)

    def test_pattern_invocation(self):
        self._setup_circle()
        self.repl("circle doofus")
        self.repl("set doofus radius to 3")
        result = self.repl("area of doofus")
        self.assertAlmostEqual(float(result), 28.26, places=1)

    def test_look_around_in_type(self):
        self.repl("type circle")
        self.repl("enter circle")
        self.repl("box radius")
        self.repl("enter device area")
        self.repl("exit")
        result = self.repl("look around")
        self.assertIn("a box named 'radius'", result)
        self.assertIn("a device named 'area'", result)

    def test_look_around_instance_in_room(self):
        self._setup_circle()
        self.repl("circle doofus")
        result = self.repl("look around")
        self.assertIn("a circle named 'doofus'", result)

    def test_two_instances_independent(self):
        self._setup_circle()
        self.repl("circle doofus")
        self.repl("set doofus radius to 3")
        self.repl("circle bigone")
        self.repl("set bigone radius to 10")
        r1 = float(self.repl("run doofus' area"))
        r2 = float(self.repl("run bigone' area"))
        self.assertAlmostEqual(r1, 28.26, places=1)
        self.assertAlmostEqual(r2, 314.0, places=0)


# ---------------------------------------------------------------------------
# 9. Chain literals
# ---------------------------------------------------------------------------

class TestChainLiterals(unittest.TestCase):
    """'set chain NAME to V1 and V2 and V3' creates a chain with inline values."""

    def setUp(self):
        self.ide, self.interp, self.repl = make_repl()
        self.repl("palace test")
        self.repl("enter lobby")

    def _lobby(self):
        return self.ide.ast["palaces"]["test"]["rooms"]["lobby"]

    def _chain(self, name):
        return self._lobby()["contents"][name]

    def test_string_chain(self):
        self.assertEqual(
            self.repl("set chain alphabet stop to a and b and c over"), "yes")
        ch = self._chain("alphabet")
        self.assertEqual(ch["type"], "chain")
        self.assertEqual(ch["value_type"], "string")
        self.assertEqual([lk["value"] for lk in ch["links"]], ["a", "b", "c"])

    def test_number_chain(self):
        self.assertEqual(self.repl("set chain scores to 1 and 2 and 3"), "yes")
        ch = self._chain("scores")
        self.assertEqual(ch["value_type"], "number")
        self.assertEqual([lk["value"] for lk in ch["links"]], [1, 2, 3])

    def test_boolean_chain(self):
        self.assertEqual(self.repl("set chain flags to true and false and true"), "yes")
        ch = self._chain("flags")
        self.assertEqual(ch["value_type"], "boolean")
        self.assertEqual([lk["value"] for lk in ch["links"]], [True, False, True])

    def test_single_value(self):
        self.assertEqual(self.repl("set chain solo to hello"), "yes")
        ch = self._chain("solo")
        self.assertEqual(len(ch["links"]), 1)
        self.assertEqual(ch["links"][0]["value"], "hello")

    def test_multi_word_name_stop(self):
        self.repl("set chain high scores stop to 10 and 20 and 30")
        self.assertIn("high scores", self._lobby()["contents"])
        ch = self._chain("high scores")
        self.assertEqual([lk["value"] for lk in ch["links"]], [10, 20, 30])

    def test_name_without_stop(self):
        self.repl("set chain primes to 2 and 3 and 5 and 7")
        ch = self._chain("primes")
        self.assertEqual(len(ch["links"]), 4)

    def test_overwrites_existing_links(self):
        self.repl("chain sequence")
        self.repl("append 99 to sequence")
        self.repl("set chain sequence to 1 and 2")
        ch = self._chain("sequence")
        self.assertEqual([lk["value"] for lk in ch["links"]], [1, 2])

    def test_chain_is_queryable_after_literal(self):
        self.repl("set chain abc to 10 and 20 and 30")
        self.assertEqual(self.repl("length of abc?"), "3")

    def test_stop_on_last_value(self):
        # 'stop' at end of last value is stripped by _parse_value
        self.repl("set chain letters to x and y and z stop")
        ch = self._chain("letters")
        self.assertEqual([lk["value"] for lk in ch["links"]], ["x", "y", "z"])


# ---------------------------------------------------------------------------
# 10. Look around
# ---------------------------------------------------------------------------

class TestLookAround(unittest.TestCase):
    """'look around' describes items in the current context."""

    def setUp(self):
        self.ide, self.interp, self.repl = make_repl()
        self.repl("palace test")
        self.repl("enter lobby")

    def test_empty_room(self):
        result = self.repl("look around")
        self.assertIn("room 'lobby'", result)
        self.assertIn("You see nothing", result)

    def test_room_with_device_and_box(self):
        self.repl("device adder")
        self.repl("box score")
        result = self.repl("look around")
        self.assertIn("a device named 'adder'", result)
        self.assertIn("a box named 'score'", result)

    def test_room_multi_word_name_uses_stop(self):
        self.repl("chain sequence")
        self.repl("box fruit")
        result = self.repl("look around")
        # multiple items are separated by ", "
        self.assertIn("a chain named 'sequence'", result)
        self.assertIn("a box named 'fruit'", result)

    def test_room_single_item_no_stop(self):
        self.repl("box fruit")
        result = self.repl("look around")
        self.assertIn("a box named 'fruit'", result)
        self.assertIn("You see:", result)

    def test_device_context_shows_boxes(self):
        self.repl("device calc")
        self.repl("enter calc")
        self.repl("box temp")
        result = self.repl("look around")
        self.assertIn("a box named 'temp'", result)
        # the device itself should not appear (we're inside it)
        self.assertNotIn("a device named 'calc'", result)

    def test_device_context_shows_input_and_process(self):
        self.repl("device calc")
        self.repl("enter calc")
        result = self.repl("look around")
        # always shows input box and process chain
        self.assertIn("a box named 'input'", result)
        self.assertIn("a chain named 'process'", result)

    def test_various_types_in_room(self):
        self.repl("chain log")
        self.repl("bag store")
        self.repl("box counter")
        result = self.repl("look around")
        self.assertIn("a chain named 'log'", result)
        self.assertIn("a bag named 'store'", result)
        self.assertIn("a box named 'counter'", result)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
