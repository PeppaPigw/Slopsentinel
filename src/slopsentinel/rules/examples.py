from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuleExample:
    language: str
    bad: str
    good: str | None = None
    notes: str | None = None


EXAMPLES: dict[str, RuleExample] = {
    "A03": RuleExample(
        language="python",
        bad="# We need to ensure this is safe\nx = 1\n",
        good="# Keep comments that add *new* information.\nx = 1\n",
        notes="A03 flags overly polite / non-actionable AI narration in comments.",
    ),
    "B03": RuleExample(
        language="typescript",
        bad=(
            'console.log("a")\n'
            'console.log("b")\n'
            'console.log("c")\n'
            'console.log("d")\n'
            'console.log("e")\n'
        ),
        good=(
            'logger.debug("a")\n'
            'logger.debug("b")\n'
            'logger.debug("c")\n'
            'logger.debug("d")\n'
            'logger.debug("e")\n'
        ),
    ),
    "B06": RuleExample(
        language="typescript",
        bad="interface Foo {}\n\ntype Bar = {};\n",
        good="interface Foo { id: string }\n\ntype Bar = { id: string };\n",
    ),
    "B07": RuleExample(
        language="typescript",
        bad="const a = value as any;\nconst b = other as any;\nconst c = third as any;\n",
        good="const a: unknown = value;\n// Narrow types safely instead of `as any`.\n",
    ),
    "C04": RuleExample(
        language="python",
        bad=(
            "from typing import Optional\n\n"
            "def f(a: Optional[int], b: Optional[int], c: Optional[int], d: Optional[int], e: Optional[int]) -> Optional[int]:\n"
            "    return a or b or c or d or e\n"
        ),
        good=(
            "def f(a: int | None, b: int | None, c: int | None, d: int | None, e: int | None) -> int | None:\n"
            "    return a or b or c or d or e\n"
        ),
    ),
    "C06": RuleExample(
        language="python",
        bad="def add(x: int, y: int):\n    return x + y\n",
        good="def add(x: int, y: int) -> int:\n    return x + y\n",
    ),
    "C08": RuleExample(
        language="python",
        bad=(
            "from typing import Any\n\n"
            "def f(x: Any) -> Any:\n"
            "    y: Any = x\n"
            "    z: Any = y\n"
            "    a: Any = z\n"
            "    return a\n"
        ),
        good=(
            "def f(x: object) -> object:\n"
            "    y: object = x\n"
            "    return y\n"
        ),
    ),
    "C11": RuleExample(
        language="python",
        bad='handler = lambda x: do_something_really_long_name(x, option_one=True, option_two=False, option_three="abc")\n',
        good=(
            "def handler(x: int) -> int:\n"
            "    return do_something_really_long_name(x, option_one=True, option_two=False, option_three=\"abc\")\n"
        ),
    ),
    "D02": RuleExample(
        language="python",
        bad="print('a')\nprint('b')\nprint('c')\nprint('d')\nprint('e')\n",
        good="logger.debug('a')\n# ...\n",
    ),
    "D05": RuleExample(
        language="python",
        bad="counter = 0\n\ndef inc() -> None:\n    global counter\n    counter += 1\n",
        good="class Counter:\n    def __init__(self) -> None:\n        self.value = 0\n",
    ),
    "D06": RuleExample(
        language="python",
        bad="result = eval(user_input)\n",
        good="result = int(user_input)  # or use a safe parser\n",
        notes="Avoid exec/eval on untrusted input; it is a security risk.",
    ),
    "E06": RuleExample(
        language="python",
        bad=(
            'print("hello world")\n'
            'print("hello world")\n'
            'print("hello world")\n'
        ),
        good=(
            'HELLO_WORLD = "hello world"\n'
            "print(HELLO_WORLD)\n"
            "print(HELLO_WORLD)\n"
            "print(HELLO_WORLD)\n"
        ),
        notes="E06 flags repeated string literals that should be extracted into constants to reduce drift.",
    ),
    "E11": RuleExample(
        language="python",
        bad="if condition:\n    return True\nelse:\n    return False\n",
        good="return condition\n",
        notes="E11 flags redundant boolean returns that can be simplified.",
    ),
    "G02": RuleExample(
        language="go",
        bad='return errors.New("Bad thing.")\n',
        good='return errors.New("bad thing")\n',
        notes="Idiomatic Go error strings are lowercase and punctuation-free.",
    ),
    "G03": RuleExample(
        language="go",
        bad='fmt.Println("DEBUG: reached here")\n',
        good='logger.Debug("reached here") // behind a debug flag\n',
    ),
    "G04": RuleExample(
        language="go",
        bad="ctx := context.TODO()\n",
        good="ctx := context.Background() // top-level only; prefer threading ctx in\n",
    ),
    "G05": RuleExample(
        language="go",
        bad="time.Sleep(2 * time.Second)\n",
        good="time.Sleep(backoff.Next()) // bounded + documented, or use sync primitives\n",
    ),
    "R02": RuleExample(
        language="rust",
        bad="let value = maybe_value.unwrap();\n",
        good="let value = maybe_value.ok_or(MyError::MissingValue)?;\n",
    ),
    "R03": RuleExample(
        language="rust",
        bad='todo!("implement")\n',
        good="return Err(MyError::NotImplemented);\n",
    ),
    "R04": RuleExample(
        language="rust",
        bad="dbg!(value);\n",
        good="tracing::debug!(?value);\n",
    ),
    "R05": RuleExample(
        language="rust",
        bad="unsafe { do_thing(ptr) }\n",
        good="do_thing_safe(&mut value) // prefer safe wrappers; document invariants if unsafe is required\n",
    ),
    "J01": RuleExample(
        language="java",
        bad='System.out.println("DEBUG");\n',
        good='logger.debug("...");\n',
    ),
    "K01": RuleExample(
        language="kotlin",
        bad='TODO("implement")\n',
        good='throw NotImplementedError("implement")\n',
        notes="Prefer explicit errors + tracking issues over TODO() placeholders in shipped code.",
    ),
    "Y01": RuleExample(
        language="ruby",
        bad="binding.pry\n",
        good="# remove debugger hooks before commit\n",
    ),
    "P01": RuleExample(
        language="php",
        bad="var_dump($x);\n",
        good="error_log(print_r($x, true)); // behind env guard\n",
    ),
    "X01": RuleExample(
        language="text",
        bad="src/foo.py and src/bar.py contain identical code bodies.\n",
        good="Extract shared code into a helper/module.\n",
    ),
    "X02": RuleExample(
        language="text",
        bad="src/foo_bar.py, src/fooBar.py mixed in same directory.\n",
        good="Pick one convention per directory/language (e.g. snake_case for Python).\n",
    ),
    "X03": RuleExample(
        language="text",
        bad="Many Python files share the same structural skeleton (same function/class shapes, only names differ).\n",
        good="Extract shared helpers or generate templates instead of duplicating scaffolds.\n",
    ),
}
