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
        return interp.execute(result["action"])

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
        ("where am I?",                                                "You are in device 'adder' in room 'lobby' in palace 'fibonacci'"),
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
                         "You are in room 'vault' in wing 'east' in palace 'manor'")

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

    def test_append_to_multi_word_chain_name(self):
        self.repl("chain sea quest stop")
        self.assertEqual(self.repl("append 1 to sea quest"), "yes")
        ch = self._lobby()["contents"]["sea quest"]
        self.assertEqual(len(ch["links"]), 1)
        self.assertEqual(ch["links"][0]["value"], 1)

    def test_append_link_to_multi_word_chain_name(self):
        self.repl("chain sea quest stop")
        self.assertEqual(self.repl("append link to sea quest"), "yes")
        ch = self._lobby()["contents"]["sea quest"]
        self.assertEqual(len(ch["links"]), 1)

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
        # chains and bags only hold scalar value types
        self.assertIn("unknown type", self.repl("chain of widgets foo"))
        self.assertIn("unknown type", self.repl("bag of widgets foo"))

    def test_box_accepts_builtin_type(self):
        self.assertEqual(self.repl("box of chain coord"), "yes")
        box = self._lobby()["contents"]["coord"]
        self.assertEqual(box["type"], "box")
        self.assertEqual(box["value_type"], "chain")

    def test_box_accepts_user_type(self):
        self.repl("type point")
        self.assertEqual(self.repl("box of point origin"), "yes")
        box = self._lobby()["contents"]["origin"]
        self.assertEqual(box["value_type"], "point")


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

    def test_set_box_name_creates_if_not_found(self):
        self.assertEqual(self.repl("set box phantom to 1"), "yes")
        box = self._lobby()["contents"]["phantom"]
        self.assertEqual(box["type"], "box")
        self.assertEqual(box["value"], 1)

    def test_set_box_typed_named_creates_and_sets(self):
        self.assertEqual(self.repl("set box of number radius stop to 10"), "yes")
        box = self._lobby()["contents"]["radius"]
        self.assertEqual(box["value_type"], "number")
        self.assertEqual(box["value"], 10)

    def test_set_box_named_stop_creates_and_sets(self):
        self.assertEqual(self.repl("set box score stop to 42"), "yes")
        box = self._lobby()["contents"]["score"]
        self.assertEqual(box["type"], "box")
        self.assertEqual(box["value"], 42)

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

    def _pattern_tokens(self, type_name: str, device_name: str):
        """Extract token list from a pattern object stored on a type's device."""
        pat = self._type(type_name)[device_name]["pattern"]
        if isinstance(pat, list):
            return pat
        return [lnk["value"] for lnk in pat["chain"]["links"]]

    def _setup_circle(self):
        for cmd in [
            "type circle",
            "enter circle",
            "box radius",
            "enter device area",
            "step 1 return 3.14 times radius times radius",
            "set pattern to name of parent",
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
        self.assertIn("radius", self._type("circle"))
        # field should NOT appear in room
        self.assertNotIn("radius", self._lobby()["contents"])

    def test_enter_device_in_type(self):
        self.repl("type circle")
        self.repl("enter circle")
        self.repl("enter device area")
        self.assertEqual(self.ide.current["device"], "area")
        self.assertIn("area", self._type("circle"))

    def test_step_shorthand_adds_to_process(self):
        self.repl("type circle")
        self.repl("enter circle")
        self.repl("enter device area")
        self.repl("step 1 return 3.14 times radius times radius")
        process = self._type("circle")["area"]["process"]
        self.assertEqual(process[0]["type"], "command")
        self.assertEqual(process[0]["operator"], "return")
        # expression is fully nested: (3.14 * radius) * radius  (left-associative)
        # all leaves are typed objects
        expr = process[0]["arguments"][0]
        self.assertEqual(expr["operator"], "multiply")
        self.assertEqual(expr["arguments"][1], {"type": "reference", "name": "radius"})
        inner = expr["arguments"][0]
        self.assertEqual(inner["operator"], "multiply")
        self.assertEqual(inner["arguments"][0], {"type": "number", "value": 3.14})
        self.assertEqual(inner["arguments"][1], {"type": "reference", "name": "radius"})

    def test_set_pattern(self):
        self.repl("type circle")
        self.repl("enter circle")
        self.repl("enter device area")
        self.repl("set pattern to name of parent")
        self.assertEqual(self._pattern_tokens("circle", "area"), ["<name>", "of", "<parent>"])

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

    def test_enter_instance(self):
        self._setup_circle()
        self.repl("circle doofus")
        self.assertEqual(self.repl("enter doofus"), "yes")
        self.assertEqual(self.ide.current["instance"], "doofus")

    def test_enter_instance_sets_type_in_op(self):
        self._setup_circle()
        self.repl("circle doofus")
        result = self.ide.process("enter doofus")
        self.assertEqual(result["action"]["operator"], "enter.instance")
        self.assertEqual(result["action"]["type"], "circle")

    def test_instantiate_copies_fields(self):
        self._setup_circle()
        self.repl("circle doofus")
        self.assertIn("radius", self._lobby()["contents"]["doofus"])

    def _doofus_radius(self):
        return self._lobby()["contents"]["doofus"]["radius"]["value"]

    def test_set_instance_field(self):
        self._setup_circle()
        self.repl("circle doofus")
        self.assertEqual(self.repl("set doofus radius to 3"), "yes")
        self.assertEqual(self._doofus_radius(), 3)

    def test_set_instance_field_possessive(self):
        self._setup_circle()
        self.repl("circle doofus")
        self.assertEqual(self.repl("set doofus's radius to 7"), "yes")
        self.assertEqual(self._doofus_radius(), 7)

    def test_set_instance_field_after_enter(self):
        self._setup_circle()
        self.repl("circle doofus")
        self.repl("enter doofus")
        self.assertEqual(self.repl("set radius to 5"), "yes")
        self.assertEqual(self._doofus_radius(), 5)

    def test_run_instance_device(self):
        self._setup_circle()
        self.repl("circle doofus")
        self.repl("set doofus radius to 3")
        result = self.repl("run doofus' area")
        self.assertAlmostEqual(float(result), 28.26, places=1)

    def test_run_instance_device_no_apostrophe(self):
        self._setup_circle()
        self.repl("circle doofus")
        self.repl("set doofus radius to 3")
        result = self.repl("run doofus area")
        self.assertAlmostEqual(float(result), 28.26, places=1)

    def test_pattern_invocation(self):
        self._setup_circle()
        self.repl("circle doofus")
        self.repl("set doofus radius to 3")
        result = self.repl("area of doofus")
        self.assertAlmostEqual(float(result), 28.26, places=1)

    def test_pattern_start_stop_delimiters(self):
        # 'start' prefix and 'stop' suffix are stripped from the stored pattern
        self.repl("type circle")
        self.repl("enter circle")
        self.repl("enter device area")
        self.repl("set pattern to start name of parent stop")
        self.assertEqual(self._pattern_tokens("circle", "area"), ["<name>", "of", "<parent>"])

    def test_pattern_with_input_slot(self):
        # 'input' slot captures a value passed to the device
        for cmd in [
            "type vector",
            "enter vector",
            "box x",
            "enter device scale",
            "step 1 return input times x",
            "set pattern to name parent by input",
            "exit",
            "exit",
        ]:
            self.repl(cmd)
        self.repl("vector v")
        self.repl("set v x to 3")
        result = self.repl("scale v by 4")
        self.assertEqual(result, "12")

    def test_pattern_input_slot_full_example(self):
        # The user's stated example: "get name of parent in input dimensions"
        for cmd in [
            "type vector",
            "enter vector",
            "box dim",
            "enter device magnitude",
            "step 1 return input times dim",
            "set pattern to get name of parent in input dimensions",
            "exit",
            "exit",
        ]:
            self.repl(cmd)
        self.repl("vector distance")
        self.repl("set distance dim to 3")
        result = self.repl("get magnitude of distance in 4 dimensions")
        self.assertEqual(result, "12")

    def test_pattern_only_matches_correct_type(self):
        # Pattern on 'circle' should not fire for a non-circle instance
        self._setup_circle()
        self.repl("circle doofus")
        self.repl("type square")
        self.repl("square block")
        # "area of block" — block is not a circle, so pattern should not match
        result = self.repl("area of block")
        self.assertNotEqual(result, "yes")  # won't be a run result
        self.assertIn("unrecognized", result.lower())

    def test_pattern_scoped_to_palace(self):
        # Pattern stored in one palace is not accessible in another
        self._setup_circle()
        self.repl("circle doofus")
        result_palace1 = self.repl("area of doofus")
        self.assertNotIn("unrecognized", result_palace1.lower())
        # Switch to a different palace
        self.repl("palace otherplace")
        self.repl("circle doofus2")
        # No pattern defined here, so should be unrecognized
        result_palace2 = self.repl("area of doofus2")
        self.assertIn("unrecognized", result_palace2.lower())

    # --- optional keyword ---

    def test_optional_keyword_stored_as_question_mark(self):
        # 'optional X' in the spec → 'X?' in the stored list
        self.repl("type circle")
        self.repl("enter circle")
        self.repl("enter device area")
        self.repl("set pattern to name optional of parent")
        self.assertEqual(self._pattern_tokens("circle", "area"),
                         ["<name>", "of?", "<parent>"])

    def test_optional_literal_matches_with_and_without(self):
        # Pattern "get name optional of parent" should match both
        # "get area of doofus" and "get area doofus".
        # Prefixing with "get" avoids collision with the instantiation Earley rule
        # (which would parse "area doofus" as type=area, instance=doofus).
        self._setup_circle()
        self.repl("circle doofus")
        self.repl("set doofus radius to 3")
        # Override the pattern
        self.repl("enter circle")
        self.repl("enter device area")
        self.repl("set pattern to get name optional of parent")
        self.repl("exit")
        self.repl("exit")
        result_with    = self.repl("get area of doofus")
        result_without = self.repl("get area doofus")
        self.assertAlmostEqual(float(result_with),    28.26, places=1)
        self.assertAlmostEqual(float(result_without), 28.26, places=1)

    def test_optional_slot_matches_with_and_without(self):
        # Pattern "name parent optional input" — input slot is optional.
        # Device returns input when given, or 0 when absent (input=None → 0 via
        # a box default).
        for cmd in [
            "type scaler", "enter scaler", "box factor",
            "enter device apply",
            "step 1 return input times factor",
            "set pattern to name parent optional input",
            "exit", "exit",
        ]:
            self.repl(cmd)
        self.repl("scaler s")
        self.repl("set s factor to 7")
        # With input the device runs normally
        self.assertEqual(self.repl("apply s 3"), "21")
        # Without input the match still succeeds (input=None passed to device)
        result_no_input = self.repl("apply s")
        # Result is "None" (None * 7 = None propagated) — the key point is the
        # pattern matched rather than returning "unrecognized"
        self.assertNotIn("unrecognized", result_no_input.lower())

    # --- escape keyword ---

    def test_escape_keyword_stored_as_literal(self):
        # 'escape name' stores the word "name" as a plain literal
        self.repl("type circle")
        self.repl("enter circle")
        self.repl("enter device area")
        self.repl("set pattern to escape name of parent")
        self.assertEqual(self._pattern_tokens("circle", "area"),
                         ["name", "of", "<parent>"])

    def test_escape_prevents_slot_interpretation(self):
        # Pattern "escape name of parent" matches "name of doofus" literally
        for cmd in [
            "type circle", "enter circle", "box radius",
            "enter device area",
            "step 1 return 3.14 times radius times radius",
            "set pattern to escape name of parent",
            "exit", "exit",
        ]:
            self.repl(cmd)
        self.repl("circle doofus")
        self.repl("set doofus radius to 3")
        # Literal "name" in the pattern, not the device name "area"
        result = self.repl("name of doofus")
        self.assertAlmostEqual(float(result), 28.26, places=1)
        # "area of doofus" should NOT match (pattern requires literal "name")
        bad = self.repl("area of doofus")
        self.assertIn("unrecognized", bad.lower())

    def test_escape_optional_combo(self):
        # 'optional escape optional' → literal word "optional" made optional
        self.repl("type circle")
        self.repl("enter circle")
        self.repl("enter device area")
        self.repl("set pattern to name optional escape optional parent")
        self.assertEqual(self._pattern_tokens("circle", "area"),
                         ["<name>", "optional?", "<parent>"])

    # --- pattern chain navigation ---

    def test_enter_pattern_sets_nav_frame(self):
        self._setup_circle()
        self.repl("enter circle")
        self.repl("enter device area")
        self.assertEqual(self.repl("enter pattern"), "yes")
        self.assertEqual(self.ide.nav_stack[-1][0]["kind"], "pattern_chain")

    def test_exit_pattern_returns_to_device(self):
        self._setup_circle()
        self.repl("enter circle")
        self.repl("enter device area")
        self.repl("enter pattern")
        self.repl("exit")
        self.assertEqual(self.ide.current["device"], "area")
        self.assertNotEqual(self.ide.nav_stack[-1][0]["kind"], "pattern_chain")

    def test_enter_pattern_no_pattern_errors(self):
        self.repl("type circle")
        self.repl("enter circle")
        self.repl("enter device area")
        result = self.repl("enter pattern")
        self.assertIn("no pattern", result.lower())

    def test_look_around_in_pattern_chain_shows_links(self):
        self._setup_circle()
        self.repl("enter circle")
        self.repl("enter device area")
        self.repl("enter pattern")
        result = self.repl("look around")
        # Default pattern is ["<name>", "of", "<parent>"] — 3 links
        self.assertIn("link 1", result)
        self.assertIn("link 2", result)
        self.assertIn("link 3", result)
        self.assertIn("<name>", result)
        self.assertIn("<parent>", result)

    def test_look_around_in_device_shows_pattern_chain_entry(self):
        self._setup_circle()
        self.repl("enter circle")
        self.repl("enter device area")
        result = self.repl("look around")
        self.assertIn("pattern chain", result)
        self.assertIn("3 links", result)

    def test_set_pattern_link_value(self):
        self._setup_circle()
        self.repl("enter circle")
        self.repl("enter device area")
        self.repl("enter pattern")
        self.repl("set link 2 to of?")
        self.assertEqual(self._pattern_tokens("circle", "area"),
                         ["<name>", "of?", "<parent>"])

    def test_set_pattern_link_slot_value(self):
        self._setup_circle()
        self.repl("enter circle")
        self.repl("enter device area")
        self.repl("enter pattern")
        self.repl("set link 1 to <parent>")
        self.assertEqual(self._pattern_tokens("circle", "area"),
                         ["<parent>", "of", "<parent>"])

    def test_append_link_in_pattern_chain(self):
        self._setup_circle()
        self.repl("enter circle")
        self.repl("enter device area")
        self.repl("enter pattern")
        self.repl("append link")
        tokens = self._pattern_tokens("circle", "area")
        self.assertEqual(len(tokens), 4)
        self.assertIsNone(tokens[3])

    def test_whereami_in_pattern_chain(self):
        self._setup_circle()
        self.repl("enter circle")
        self.repl("enter device area")
        self.repl("enter pattern")
        result = self.repl("where am i")
        self.assertIn("pattern chain", result)

    def test_pattern_stored_as_palace_format(self):
        # Verify new JSON structure: type=pattern, chain with links
        self._setup_circle()
        pat = self._type("circle")["area"]["pattern"]
        self.assertEqual(pat["type"], "pattern")
        self.assertEqual(pat["chain"]["type"], "chain")
        self.assertEqual(pat["chain"]["value_type"], "string")
        self.assertEqual(len(pat["chain"]["links"]), 3)
        self.assertEqual(pat["chain"]["links"][0]["value"], "<name>")
        self.assertEqual(pat["chain"]["links"][1]["value"], "of")
        self.assertEqual(pat["chain"]["links"][2]["value"], "<parent>")

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

    def test_look_around_inside_instance_shows_fields(self):
        self._setup_circle()
        self.repl("circle doofus")
        self.repl("enter doofus")
        result = self.repl("look around")
        # Should describe the instance, not the surrounding room
        self.assertIn("doofus", result)
        self.assertNotIn("a circle named 'doofus'", result)  # room view
        self.assertIn("radius", result)                      # instance field

    def test_whereami_inside_instance(self):
        self._setup_circle()
        self.repl("circle doofus")
        self.repl("enter doofus")
        result = self.repl("where am i")
        self.assertIn("doofus", result)

    # --- type inheritance ---

    def test_type_from_one_line(self):
        self.assertEqual(self.repl("type conga line stop from chain"), "yes")
        self.assertIn("conga line", self.ide.ast["palaces"]["mypalace"]["types"])
        self.assertEqual(self._type("conga line")["parent"], "chain")

    def test_type_from_one_line_single_word(self):
        self.assertEqual(self.repl("type sequence from chain"), "yes")
        self.assertEqual(self._type("sequence")["parent"], "chain")

    def test_type_from_two_line_with_possessive(self):
        self.repl("type square dance")
        self.assertEqual(self._type("square dance")["parent"], "bag")  # default
        self.assertEqual(self.repl("set square dance's parent to conga line"), "yes")
        self.assertEqual(self._type("square dance")["parent"], "conga line")

    def test_type_from_two_line_without_possessive(self):
        self.repl("type waltz")
        self.repl("set waltz parent to chain")
        self.assertEqual(self._type("waltz")["parent"], "chain")

    def test_set_parent_on_unknown_type_errors(self):
        result = self.repl("set ghost parent to chain")
        self.assertIn("no type", result)

    def test_type_multi_word_name_no_inheritance(self):
        self.assertEqual(self.repl("type square dance"), "yes")
        self.assertIn("square dance", self.ide.ast["palaces"]["mypalace"]["types"])

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

    # --- inheritance: instance gets all ancestor fields ---

    def test_child_instance_has_parent_fields(self):
        # parent type: shape with a colour field
        self.repl("type shape")
        self.repl("enter shape")
        self.repl("box colour")
        self.repl("exit")
        # child type: circle inherits shape, adds radius
        self.repl("type circle from shape")
        self.repl("enter circle")
        self.repl("box radius")
        self.repl("exit")
        # instance should carry both fields
        self.repl("circle c")
        inst = self._lobby()["contents"]["c"]
        self.assertIn("colour", inst)
        self.assertIn("radius", inst)

    def test_child_overrides_parent_field(self):
        # parent defines x with value 0; child redefines x with value 99
        self.repl("type base")
        self.repl("enter base")
        self.repl("box x")
        self.repl("set x to 0")
        self.repl("exit")
        self.repl("type derived from base")
        self.repl("enter derived")
        self.repl("box x")
        self.repl("set x to 99")
        self.repl("exit")
        self.repl("derived obj")
        self.assertEqual(self._lobby()["contents"]["obj"]["x"]["value"], 99)

    def test_three_generation_chain(self):
        # grandparent → parent → child; all fields present in instance
        self.repl("type a")
        self.repl("enter a")
        self.repl("box alpha")
        self.repl("exit")
        self.repl("type b from a")
        self.repl("enter b")
        self.repl("box beta")
        self.repl("exit")
        self.repl("type c from b")
        self.repl("enter c")
        self.repl("box gamma")
        self.repl("exit")
        self.repl("c obj")
        inst = self._lobby()["contents"]["obj"]
        self.assertIn("alpha", inst)
        self.assertIn("beta",  inst)
        self.assertIn("gamma", inst)

    def test_parent_only_instance_unchanged(self):
        # instantiating the parent type directly should still work normally
        self.repl("type shape")
        self.repl("enter shape")
        self.repl("box colour")
        self.repl("exit")
        self.repl("type circle from shape")
        self.repl("enter circle")
        self.repl("box radius")
        self.repl("exit")
        self.repl("shape s")
        inst = self._lobby()["contents"]["s"]
        self.assertIn("colour", inst)
        self.assertNotIn("radius", inst)

    def test_inherited_fields_are_independent_copies(self):
        # two instances of a child type must not share field storage
        self.repl("type base")
        self.repl("enter base")
        self.repl("box score")
        self.repl("exit")
        self.repl("type child from base")
        self.repl("enter child")
        self.repl("box extra")
        self.repl("exit")
        self.repl("child a")
        self.repl("child b")
        self.repl("set a score to 1")
        self.repl("set b score to 2")
        contents = self._lobby()["contents"]
        self.assertEqual(contents["a"]["score"]["value"], 1)
        self.assertEqual(contents["b"]["score"]["value"], 2)

    def test_inherited_device_runs(self):
        # device defined on parent type is callable on a child instance
        self.repl("type shape")
        self.repl("enter shape")
        self.repl("enter device describe")
        self.repl("step 1 return 42")
        self.repl("set pattern to name of parent")
        self.repl("exit")
        self.repl("exit")
        self.repl("type circle from shape")
        self.repl("circle c")
        result = self.repl("describe of c")
        self.assertEqual(result, "42")

    def test_inherited_device_via_grandparent(self):
        # device defined on grandparent is callable on a grandchild instance
        self.repl("type a")
        self.repl("enter a")
        self.repl("enter device ping")
        self.repl("step 1 return 99")
        self.repl("set pattern to name of parent")
        self.repl("exit")
        self.repl("exit")
        self.repl("type b from a")
        self.repl("type c from b")
        self.repl("c obj")
        result = self.repl("ping of obj")
        self.assertEqual(result, "99")


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
# 11. Rename command
# ---------------------------------------------------------------------------

class TestRename(unittest.TestCase):
    """'rename OLD to NEW' renames things in the current context."""

    def setUp(self):
        self.ide, self.interp, self.repl = make_repl()
        self.repl("palace mypalace")
        self.repl("enter lobby")

    def _lobby(self):
        return self.ide.ast["palaces"]["mypalace"]["rooms"]["lobby"]

    def _palace(self):
        return self.ide.ast["palaces"]["mypalace"]

    # ── Room items ────────────────────────────────────────────────────────

    def test_rename_box(self):
        self.repl("box score")
        self.assertEqual(self.repl("rename score to tally"), "yes")
        self.assertNotIn("score", self._lobby()["contents"])
        self.assertIn("tally", self._lobby()["contents"])

    def test_rename_chain(self):
        self.repl("chain log")
        self.assertEqual(self.repl("rename log to history"), "yes")
        self.assertNotIn("log", self._lobby()["contents"])
        self.assertIn("history", self._lobby()["contents"])

    def test_rename_device(self):
        self.repl("device calc")
        self.assertEqual(self.repl("rename calc to compute"), "yes")
        self.assertIn("compute", self._lobby()["contents"])

    def test_rename_preserves_data(self):
        self.repl("box score")
        self.repl("set score to 42")
        self.repl("rename score to tally")
        self.assertEqual(self._lobby()["contents"]["tally"]["value"], 42)

    def test_rename_with_stop_separator(self):
        self.repl("box score")
        self.assertEqual(self.repl("rename score stop tally"), "yes")
        self.assertIn("tally", self._lobby()["contents"])

    def test_rename_multiword_old_name_with_stop(self):
        self.repl("box high score stop")
        self.assertEqual(self.repl("rename high score stop to best score"), "yes")
        self.assertNotIn("high score", self._lobby()["contents"])
        self.assertIn("best score", self._lobby()["contents"])

    def test_rename_same_name_is_noop(self):
        self.repl("box score")
        self.assertEqual(self.repl("rename score to score"), "yes")
        self.assertIn("score", self._lobby()["contents"])

    def test_rename_updates_current_device(self):
        self.repl("device calc")
        self.repl("enter calc")
        self.repl("rename calc to compute")
        self.assertEqual(self.ide.current["device"], "compute")

    # ── Rooms ─────────────────────────────────────────────────────────────

    def test_rename_room(self):
        self.repl("room vault")
        self.assertEqual(self.repl("rename vault to storage"), "yes")
        rooms = self._palace()["rooms"]
        self.assertNotIn("vault", rooms)
        self.assertIn("storage", rooms)

    def test_rename_current_room_updates_context(self):
        self.repl("room vault")
        self.repl("enter vault")
        self.repl("rename vault to storage")
        self.assertEqual(self.ide.current["room"], "storage")

    # ── Wings ─────────────────────────────────────────────────────────────

    def test_rename_wing(self):
        self.repl("wing east")
        self.assertEqual(self.repl("rename east to west"), "yes")
        wings = self._palace()["wings"]
        self.assertNotIn("east", wings)
        self.assertIn("west", wings)

    # ── Types ─────────────────────────────────────────────────────────────

    def test_rename_type(self):
        self.repl("type point")
        self.assertEqual(self.repl("rename point to vertex"), "yes")
        types = self._palace()["types"]
        self.assertNotIn("point", types)
        self.assertIn("vertex", types)

    def test_rename_type_updates_context(self):
        self.repl("type point")
        self.repl("enter point")
        self.repl("rename point to vertex")
        self.assertEqual(self.ide.current["type_def"], "vertex")

    # ── Error cases ───────────────────────────────────────────────────────

    def test_rename_not_found(self):
        result = self.repl("rename ghost to phantom")
        self.assertIn("cannot find", result)

    def test_rename_new_name_already_in_use(self):
        self.repl("box score")
        self.repl("box tally")
        result = self.repl("rename score to tally")
        self.assertIn("already in use", result)

    def test_rename_new_name_is_type(self):
        self.repl("box score")
        result = self.repl("rename score to chain")
        self.assertIn("type name", result)

    def test_rename_room_new_name_is_type(self):
        self.repl("room vault")
        result = self.repl("rename vault to device")
        self.assertIn("type name", result)


# ---------------------------------------------------------------------------
# 12. Name conflict / uniqueness rules
# ---------------------------------------------------------------------------

class TestNameConflicts(unittest.TestCase):
    """Verifies that reserved and conflicting names are rejected."""

    def setUp(self):
        self.ide, self.interp, self.repl = make_repl()
        # every test starts inside a palace lobby
        self.repl("palace mypalace")
        self.repl("enter lobby")

    def _lobby(self):
        return self.ide.ast["palaces"]["mypalace"]["rooms"]["lobby"]

    # ── Palace names ──────────────────────────────────────────────────────

    def test_palace_cannot_be_builtin_type(self):
        _, _, r2 = make_repl()
        result = r2("palace box")
        self.assertIn("built-in type", result)

    def test_palace_cannot_be_value_type(self):
        _, _, r2 = make_repl()
        result = r2("palace number")
        self.assertIn("built-in type", result)

    def test_enter_palace_cannot_be_builtin_type(self):
        _, _, r2 = make_repl()
        result = r2("enter palace chain")
        self.assertIn("built-in type", result)

    def test_enter_palace_cannot_be_value_type(self):
        _, _, r2 = make_repl()
        result = r2("enter palace string")
        self.assertIn("built-in type", result)

    # ── Wing names ────────────────────────────────────────────────────────

    def test_wing_cannot_be_builtin_type(self):
        result = self.repl("wing device")
        self.assertIn("type name", result)

    def test_wing_cannot_be_value_type(self):
        result = self.repl("wing string")
        self.assertIn("type name", result)

    def test_enter_wing_cannot_be_builtin_type(self):
        result = self.repl("enter wing bag")
        self.assertIn("type name", result)

    def test_wing_cannot_match_user_type(self):
        self.repl("type widget")
        result = self.repl("wing widget")
        self.assertIn("type name", result)

    # ── Room names ────────────────────────────────────────────────────────

    def test_room_cannot_be_builtin_type(self):
        result = self.repl("room box")
        self.assertIn("type name", result)

    def test_room_cannot_be_value_type(self):
        result = self.repl("room boolean")
        self.assertIn("type name", result)

    def test_enter_room_cannot_be_builtin_type(self):
        result = self.repl("enter room chain")
        self.assertIn("type name", result)

    def test_room_cannot_match_user_type(self):
        self.repl("type widget")
        result = self.repl("room widget")
        self.assertIn("type name", result)

    # ── Room item names vs. type names ────────────────────────────────────

    def test_box_cannot_use_builtin_type_name(self):
        result = self.repl("box chain")
        self.assertIn("type name", result)

    def test_chain_cannot_use_value_type_name(self):
        result = self.repl("chain number")
        self.assertIn("type name", result)

    def test_bag_cannot_use_builtin_type_name(self):
        result = self.repl("bag device")
        self.assertIn("type name", result)

    def test_device_cannot_use_builtin_type_name(self):
        result = self.repl("device box")
        self.assertIn("type name", result)

    def test_room_item_cannot_use_user_type_name(self):
        self.repl("type point")
        result = self.repl("box point")
        self.assertIn("type name", result)

    # ── Room item uniqueness (same room, different types) ─────────────────

    def test_chain_blocked_by_existing_box(self):
        self.repl("box foo")
        result = self.repl("chain foo")
        self.assertIn("already used as", result)

    def test_box_blocked_by_existing_chain(self):
        self.repl("chain scores")
        result = self.repl("box scores")
        self.assertIn("already used as", result)

    def test_device_blocked_by_existing_box(self):
        self.repl("box calc")
        result = self.repl("device calc")
        self.assertIn("already used as", result)

    def test_bag_blocked_by_existing_chain(self):
        self.repl("chain log")
        result = self.repl("bag log")
        self.assertIn("already used as", result)

    # ── Type creation conflicts ───────────────────────────────────────────

    def test_type_cannot_be_builtin_type(self):
        result = self.repl("type box")
        self.assertIn("built-in type", result)

    def test_type_cannot_be_value_type(self):
        result = self.repl("type number")
        self.assertIn("built-in type", result)

    def test_type_blocked_by_room_item(self):
        self.repl("box foo")
        result = self.repl("type foo")
        self.assertIn("already used as a room item", result)


# ---------------------------------------------------------------------------
# Delete command
# ---------------------------------------------------------------------------

class TestDeleteCommand(unittest.TestCase):

    def setUp(self):
        self.ide, self.interp, self.repl = make_repl()
        self.repl("palace test")
        self.repl("enter lobby")

    def _lobby(self):
        return self.ide.ast["palaces"]["test"]["rooms"]["lobby"]

    # ── delete NAME's PROP (clear value to null) ─────────────────────────

    def test_delete_prop_clears_box_value(self):
        self.repl("box dice")
        self.repl("set dice to 6")
        contents = self._lobby()["contents"]
        self.assertEqual(contents["dice"]["value"], 6)
        result = self.repl("delete dice's value")
        self.assertEqual(result, "yes")
        self.assertIsNone(contents["dice"]["value"])

    def test_delete_prop_box_still_exists(self):
        self.repl("box dice")
        self.repl("set dice to 6")
        self.repl("delete dice's value")
        self.assertIn("dice", self._lobby()["contents"])

    # ── delete NAME (remove item from room) ──────────────────────────────

    def test_delete_removes_box(self):
        self.repl("box dice")
        result = self.repl("delete dice")
        self.assertEqual(result, "yes")
        self.assertNotIn("dice", self._lobby()["contents"])

    def test_delete_removes_chain(self):
        self.repl("chain sequence")
        self.repl("append 1 to sequence")
        self.repl("append 2 to sequence")
        self.repl("delete sequence")
        self.assertNotIn("sequence", self._lobby()["contents"])

    def test_delete_unknown_item_errors(self):
        result = self.repl("delete ghost")
        self.assertNotEqual(result, "yes")

    # ── delete NAME link N (remove chain link, shift) ────────────────────

    def test_delete_link_removes_correct_link(self):
        self.repl("chain sequence")
        for v in [10, 20, 30, 40, 50]:
            self.repl(f"append {v} to sequence")
        result = self.repl("delete sequence link 3")
        self.assertEqual(result, "yes")
        links = self._lobby()["contents"]["sequence"]["links"]
        self.assertEqual(len(links), 4)
        self.assertEqual(links[0]["value"], 10)
        self.assertEqual(links[1]["value"], 20)
        # old link 4 (40) is now link 3
        self.assertEqual(links[2]["value"], 40)
        self.assertEqual(links[3]["value"], 50)

    def test_delete_link_out_of_range_errors(self):
        self.repl("chain sequence")
        self.repl("append 1 to sequence")
        result = self.repl("delete sequence link 5")
        self.assertNotEqual(result, "yes")

    def test_delete_link_on_non_chain_errors(self):
        self.repl("box dice")
        result = self.repl("delete dice link 1")
        self.assertNotEqual(result, "yes")

    # ── delete CONTAINER ITEM (remove item from bag) ──────────────────────

    def test_delete_named_removes_box_from_bag(self):
        self.repl("enter bag thingies")
        self.repl("box of numbers weight")
        self.repl("exit")
        bag = self._lobby()["contents"]["thingies"]
        self.assertIn("weight", bag["data"])
        result = self.repl("delete thingies weight")
        self.assertEqual(result, "yes")
        self.assertNotIn("weight", bag["data"])

    def test_delete_named_unknown_key_errors(self):
        self.repl("enter bag thingies")
        self.repl("exit")
        result = self.repl("delete thingies ghost")
        self.assertNotEqual(result, "yes")

    def test_delete_named_unknown_container_errors(self):
        result = self.repl("delete ghost item")
        self.assertNotEqual(result, "yes")

    # ── protected fields cannot be deleted ───────────────────────────────

    def test_cannot_delete_name_of_box(self):
        self.repl("box dice")
        result = self.repl("delete dice's name")
        self.assertNotEqual(result, "yes")
        self.assertIn("dice", self._lobby()["contents"])

    def test_cannot_delete_type_of_box(self):
        self.repl("box dice")
        result = self.repl("delete dice's type")
        self.assertNotEqual(result, "yes")
        self.assertEqual(self._lobby()["contents"]["dice"]["type"], "box")

    def test_cannot_delete_device_input(self):
        self.repl("device adder")
        result = self.repl("delete adder's input")
        self.assertNotEqual(result, "yes")
        self.assertIn("input", self._lobby()["contents"]["adder"])

    def test_cannot_delete_device_process(self):
        self.repl("device adder")
        result = self.repl("delete adder's process")
        self.assertNotEqual(result, "yes")
        self.assertIn("process", self._lobby()["contents"]["adder"])

    # ── bag context: box created inside bag lands in bag.data ─────────────

    def test_enter_bag_creates_box_in_bag_data(self):
        self.repl("enter bag thingies")
        self.repl("box of numbers weight")
        bag = self._lobby()["contents"]["thingies"]
        self.assertIn("weight", bag["data"])
        self.assertNotIn("weight", self._lobby()["contents"])

    def test_exit_bag_restores_room_context(self):
        self.repl("enter bag thingies")
        self.repl("exit")
        self.assertIsNone(self.ide.current["bag"])
        self.repl("box dice")
        self.assertIn("dice", self._lobby()["contents"])


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
