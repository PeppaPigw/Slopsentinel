# Rules Reference

SlopSentinel rules are grouped by “fingerprint family” (model artifacts) and
generic quality/hallucination heuristics.

Use `slopsentinel rules --format json` to list the exact rules available in
your installation (including plugin rules) and to see which rules are enabled
by your current config.

## Rule Groups

- **claude**: `A01`, `A02`, `A03`, `A04`, `A05`, `A06`, `A07`, `A08`, `A09`, `A10`, `A11`, `A12`
- **cursor**: `B01`, `B02`, `B03`, `B04`, `B05`, `B06`, `B07`, `B08`
- **copilot**: `C01`, `C02`, `C03`, `C04`, `C05`, `C06`, `C07`, `C08`, `C09`, `C10`, `C11`
- **gemini**: `D01`, `D02`, `D03`, `D04`, `D05`, `D06`
- **generic**: `E01`, `E02`, `E03`, `E04`, `E05`, `E06`, `E07`, `E08`, `E09`, `E10`, `E11`, `E12`
- **go**: `G01`, `G02`, `G03`, `G04`, `G05`, `G06`, `G07`
- **rust**: `R01`, `R02`, `R03`, `R04`, `R05`, `R06`, `R07`
- **java**: `J01`, `J02`, `J03`
- **kotlin**: `K01`, `K02`, `K03`
- **ruby**: `Y01`, `Y02`, `Y03`
- **php**: `P01`, `P02`, `P03`
- **crossfile**: `X01`, `X02`, `X03`, `X04`, `X05`

## Explaining a rule

Use `slopsentinel explain <RULE_ID>` to see:

- Rule metadata (severity, dimension, model label)
- How to override severity in `pyproject.toml`
- How to suppress the rule in-file
- Example snippets (for selected rules)

## Severity and Dimensions

Each rule has:

- `default_severity`: `info` | `warn` | `error`
- `dimension`: `fingerprint` | `quality` | `hallucination` | `maintainability` | `security`
- `fingerprint_model`: optional label (e.g. `claude`, `cursor`, `copilot`, `gemini`)

### Dimension counts (built-in)

| Dimension | Count |
| --- | ---: |
| `fingerprint` | 26 |
| `quality` | 31 |
| `hallucination` | 3 |
| `maintainability` | 14 |
| `security` | 6 |

The final severity can be overridden in config:

```toml
[tool.slopsentinel.rules.A03]
severity = "info"
```

## Suppressions (in-file)

Suppressions are case-insensitive. Rule IDs are canonicalized internally.

- File-level suppression:

```python
# slop: disable-file=A03,E03
```

- Same-line suppression:

```python
value = 1  # slop: disable=A03
```

- Next-line suppression:

```python
# slop: disable-next-line=C01
results = []
```

Wildcard:

```python
# slop: disable-file=all
```

## AutoFix support

`slopsentinel fix` applies conservative mechanical fixes. Currently:

- Comment-only removals: `A03`, `A06`, `A10`, `C09`, `D01`
- Python docstring trimming: `A04`
- Python-only mechanical fixes:
  - `E03` (remove simple single-binding unused imports)
  - `E04` (`except: pass` → replace `pass` with `raise`)
  - `E06` (extract repeated string literals into module-level constants)
  - `E09` (redact hardcoded credential literals into `os.environ.get(...)`)
  - `E11` (simplify `if cond: return True else: return False` → `return cond`)

If a fix is not provably safe, SlopSentinel leaves the code unchanged.

## Rule Reference

### claude

#### A01 — Co-Authored-By: Claude trailer
**Severity**: info | **Dimension**: fingerprint | **AutoFix**: ✗ | **Model**: claude

Git trailer indicates Claude-assisted commits.

Run `slopsentinel explain A01` for details and examples (when available).

#### A02 — CLAUDE.md exists
**Severity**: info | **Dimension**: fingerprint | **AutoFix**: ✗ | **Model**: claude

Project contains a CLAUDE.md memory file.

Run `slopsentinel explain A02` for details and examples (when available).

#### A03 — Overly polite comment
**Severity**: warn | **Dimension**: fingerprint | **AutoFix**: ✓ | **Model**: claude

Narrative/polite phrasing often appears in AI-generated comments.

**Bad**:
```python
# We need to ensure this is safe
x = 1
```

**Good**:
```python
# Keep comments that add *new* information.
x = 1
```

_Notes_: A03 flags overly polite / non-actionable AI narration in comments.

#### A04 — Trivial function with verbose docstring
**Severity**: warn | **Dimension**: fingerprint | **AutoFix**: ✓ | **Model**: claude

Docstring significantly larger than implementation (docstring_lines > 3× code_lines).

Run `slopsentinel explain A04` for details and examples (when available).

#### A05 — High-frequency 'robust/comprehensive/elegant'
**Severity**: warn | **Dimension**: fingerprint | **AutoFix**: ✗ | **Model**: claude

Certain adjectives frequently appear in AI-written prose within code comments/docstrings.

Run `slopsentinel explain A05` for details and examples (when available).

#### A06 — <thinking> tag leak
**Severity**: error | **Dimension**: fingerprint | **AutoFix**: ✓ | **Model**: claude

Leaked chain-of-thought tags sometimes appear in AI-generated output.

Run `slopsentinel explain A06` for details and examples (when available).

#### A07 — Over-structured exception handling
**Severity**: warn | **Dimension**: fingerprint | **AutoFix**: ✗ | **Model**: claude

Try blocks with too many except handlers often indicate over-engineered AI output.

Run `slopsentinel explain A07` for details and examples (when available).

#### A08 — Symmetric create/delete pair unused
**Severity**: warn | **Dimension**: fingerprint | **AutoFix**: ✗ | **Model**: claude

AI often generates symmetric API pairs even when unused.

Run `slopsentinel explain A08` for details and examples (when available).

#### A09 — Defensive 'at this point' comment
**Severity**: info | **Dimension**: fingerprint | **AutoFix**: ✗ | **Model**: claude

AI often adds defensive 'at this point' narrative comments.

Run `slopsentinel explain A09` for details and examples (when available).

#### A10 — Banner/separator comment
**Severity**: warn | **Dimension**: fingerprint | **AutoFix**: ✓ | **Model**: claude

Large banner separators are a common AI stylistic artifact.

Run `slopsentinel explain A10` for details and examples (when available).

#### A11 — Narrative control-flow comment
**Severity**: warn | **Dimension**: fingerprint | **AutoFix**: ✗ | **Model**: claude

Comments like 'First/Next/Finally' are common in AI explanations.

Run `slopsentinel explain A11` for details and examples (when available).

#### A12 — Placeholder apology/prod disclaimer
**Severity**: warn | **Dimension**: fingerprint | **AutoFix**: ✗ | **Model**: claude

AI often includes 'in production...' disclaimers and apologies.

Run `slopsentinel explain A12` for details and examples (when available).

### cursor

#### B01 — .cursorrules exists
**Severity**: info | **Dimension**: fingerprint | **AutoFix**: ✗ | **Model**: cursor

Cursor configuration file exists in repository root.

Run `slopsentinel explain B01` for details and examples (when available).

#### B02 — TODO spray
**Severity**: warn | **Dimension**: fingerprint | **AutoFix**: ✗ | **Model**: cursor

Three or more consecutive TODO comments suggests AI scaffolding.

Run `slopsentinel explain B02` for details and examples (when available).

#### B03 — Overuse of console.log
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗ | **Model**: cursor

Frequent console.log calls are often left behind by AI scaffolding or debugging.

**Bad**:
```typescript
console.log("a")
console.log("b")
console.log("c")
console.log("d")
console.log("e")
```

**Good**:
```typescript
logger.debug("a")
logger.debug("b")
logger.debug("c")
logger.debug("d")
logger.debug("e")
```

#### B04 — Import-then-stub pattern
**Severity**: warn | **Dimension**: fingerprint | **AutoFix**: ✗ | **Model**: cursor

Imports appear unused in a file that looks like a stub/scaffold.

Run `slopsentinel explain B04` for details and examples (when available).

#### B05 — Type assertion abuse (as any / as unknown)
**Severity**: warn | **Dimension**: fingerprint | **AutoFix**: ✗ | **Model**: cursor

Frequent type assertions can indicate AI-driven typing workarounds.

Run `slopsentinel explain B05` for details and examples (when available).

#### B06 — Empty interface/type definition
**Severity**: info | **Dimension**: quality | **AutoFix**: ✗ | **Model**: cursor

Empty TypeScript interfaces/types often indicate placeholder scaffolding.

**Bad**:
```typescript
interface Foo {}

type Bar = {};
```

**Good**:
```typescript
interface Foo { id: string }

type Bar = { id: string };
```

#### B07 — Overuse of `as any`
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗ | **Model**: cursor

Repeated `as any` assertions often indicate typing workarounds in AI-generated code.

**Bad**:
```typescript
const a = value as any;
const b = other as any;
const c = third as any;
```

**Good**:
```typescript
const a: unknown = value;
// Narrow types safely instead of `as any`.
```

#### B08 — Tab-completion repeated lines
**Severity**: warn | **Dimension**: fingerprint | **AutoFix**: ✗ | **Model**: cursor

Three or more consecutive highly-similar lines can be tab-completion artifacts.

Run `slopsentinel explain B08` for details and examples (when available).

### copilot

#### C01 — Redundant comment restates code
**Severity**: warn | **Dimension**: fingerprint | **AutoFix**: ✗ | **Model**: copilot

Comments that narrate obvious single-line code are typical AI artifacts.

Run `slopsentinel explain C01` for details and examples (when available).

#### C02 — Example Usage doctest block
**Severity**: info | **Dimension**: fingerprint | **AutoFix**: ✗ | **Model**: copilot

In-function 'Example Usage' blocks are a common AI template artifact.

Run `slopsentinel explain C02` for details and examples (when available).

#### C03 — Hallucinated import
**Severity**: error | **Dimension**: hallucination | **AutoFix**: ✗ | **Model**: copilot

Imports that don't exist in stdlib, installed packages, or the repo tree are high-risk.

Run `slopsentinel explain C03` for details and examples (when available).

#### C04 — Overuse of Optional[...] annotations
**Severity**: info | **Dimension**: quality | **AutoFix**: ✗ | **Model**: copilot

Frequent Optional[...] annotations can indicate cargo-cult typing; prefer `T | None` on Python 3.10+.

**Bad**:
```python
from typing import Optional

def f(a: Optional[int], b: Optional[int], c: Optional[int], d: Optional[int], e: Optional[int]) -> Optional[int]:
    return a or b or c or d or e
```

**Good**:
```python
def f(a: int | None, b: int | None, c: int | None, d: int | None, e: int | None) -> int | None:
    return a or b or c or d or e
```

#### C05 — Overly generic variable names
**Severity**: warn | **Dimension**: fingerprint | **AutoFix**: ✗ | **Model**: copilot

Overuse of generic names (data/result/output/temp) reduces clarity.

Run `slopsentinel explain C05` for details and examples (when available).

#### C06 — Missing return type annotation
**Severity**: info | **Dimension**: maintainability | **AutoFix**: ✗ | **Model**: copilot

Public functions without return type annotations reduce readability and type-checking effectiveness.

**Bad**:
```python
def add(x: int, y: int):
    return x + y
```

**Good**:
```python
def add(x: int, y: int) -> int:
    return x + y
```

#### C07 — Debug print left in code
**Severity**: warn | **Dimension**: fingerprint | **AutoFix**: ✗ | **Model**: copilot

DEBUG prints are often left behind by AI scaffolding.

Run `slopsentinel explain C07` for details and examples (when available).

#### C08 — Overuse of Any
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗ | **Model**: copilot

Repeated use of `Any` weakens type checking and often indicates AI-generated type scaffolding.

**Bad**:
```python
from typing import Any

def f(x: Any) -> Any:
    y: Any = x
    z: Any = y
    a: Any = z
    return a
```

**Good**:
```python
def f(x: object) -> object:
    y: object = x
    return y
```

#### C09 — Training cutoff reference
**Severity**: warn | **Dimension**: fingerprint | **AutoFix**: ✓ | **Model**: copilot

Comments referencing training data cutoff are clear AI artifacts.

Run `slopsentinel explain C09` for details and examples (when available).

#### C10 — Exception swallowing (except Exception: pass)
**Severity**: error | **Dimension**: security | **AutoFix**: ✗ | **Model**: copilot

Catching Exception and passing is a high-risk anti-pattern.

Run `slopsentinel explain C10` for details and examples (when available).

#### C11 — Overly long lambda expression
**Severity**: info | **Dimension**: maintainability | **AutoFix**: ✗ | **Model**: copilot

Very long lambda expressions are hard to read and often indicate AI-generated inline scaffolding.

**Bad**:
```python
handler = lambda x: do_something_really_long_name(x, option_one=True, option_two=False, option_three="abc")
```

**Good**:
```python
def handler(x: int) -> int:
    return do_something_really_long_name(x, option_one=True, option_two=False, option_three="abc")
```

### gemini

#### D01 — Comprehensive intro comment
**Severity**: warn | **Dimension**: fingerprint | **AutoFix**: ✓ | **Model**: gemini

Gemini-style 'Here's a comprehensive...' preambles are often AI artifacts.

Run `slopsentinel explain D01` for details and examples (when available).

#### D02 — Overuse of print()
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗ | **Model**: gemini

Many print() calls left in non-test code are often debugging artifacts.

**Bad**:
```python
print('a')
print('b')
print('c')
print('d')
print('e')
```

**Good**:
```python
logger.debug('a')
# ...
```

#### D03 — Nested ternary expression
**Severity**: warn | **Dimension**: fingerprint | **AutoFix**: ✗ | **Model**: gemini

Nested ternaries (>2 levels) harm readability and often appear in AI output.

Run `slopsentinel explain D03` for details and examples (when available).

#### D04 — Async function without await
**Severity**: warn | **Dimension**: fingerprint | **AutoFix**: ✗ | **Model**: gemini

Async functions without await indicate cargo-cult async usage.

Run `slopsentinel explain D04` for details and examples (when available).

#### D05 — Use of global keyword
**Severity**: warn | **Dimension**: maintainability | **AutoFix**: ✗ | **Model**: gemini

Using `global` inside functions is fragile and commonly appears in AI-generated code.

**Bad**:
```python
counter = 0

def inc() -> None:
    global counter
    counter += 1
```

**Good**:
```python
class Counter:
    def __init__(self) -> None:
        self.value = 0
```

#### D06 — exec/eval used
**Severity**: error | **Dimension**: security | **AutoFix**: ✗ | **Model**: gemini

Use of exec/eval is a security risk and frequently unsafe in AI-generated code.

**Bad**:
```python
result = eval(user_input)
```

**Good**:
```python
result = int(user_input)  # or use a safe parser
```

_Notes_: Avoid exec/eval on untrusted input; it is a security risk.

### generic

#### E01 — Comment/code ratio too high
**Severity**: warn | **Dimension**: hallucination | **AutoFix**: ✗

Comment-heavy files can indicate AI-generated scaffolding or over-explaining.

Run `slopsentinel explain E01` for details and examples (when available).

#### E02 — Overly defensive programming
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗

Too many scattered guard clauses beyond the leading run can indicate over-engineered AI output.

Run `slopsentinel explain E02` for details and examples (when available).

#### E03 — Unused imports
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✓

Unused imports increase confusion and can indicate AI hallucination/scaffolding.

Run `slopsentinel explain E03` for details and examples (when available).

#### E04 — Empty except block
**Severity**: error | **Dimension**: quality | **AutoFix**: ✓

Bare except/pass hides errors and makes debugging difficult.

Run `slopsentinel explain E04` for details and examples (when available).

#### E05 — Long function signature
**Severity**: info | **Dimension**: hallucination | **AutoFix**: ✗

Functions with many parameters are harder to maintain and often indicate AI over-generalization.

Run `slopsentinel explain E05` for details and examples (when available).

#### E06 — Repeated string literal
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✓

Repeated literals suggest missing constants/enums and can be AI scaffolding.

**Bad**:
```python
print("hello world")
print("hello world")
print("hello world")
```

**Good**:
```python
HELLO_WORLD = "hello world"
print(HELLO_WORLD)
print(HELLO_WORLD)
print(HELLO_WORLD)
```

_Notes_: E06 flags repeated string literals that should be extracted into constants to reduce drift.

#### E07 — Excessive nesting
**Severity**: warn | **Dimension**: maintainability | **AutoFix**: ✗

Deep nesting (>5 indentation levels) reduces readability.

Run `slopsentinel explain E07` for details and examples (when available).

#### E08 — Repeated isinstance chain
**Severity**: info | **Dimension**: maintainability | **AutoFix**: ✗

Chaining 3+ `isinstance(x, T)` checks on the same value is noisy; prefer `isinstance(x, (A, B, C))`.

Run `slopsentinel explain E08` for details and examples (when available).

#### E09 — Hardcoded credential
**Severity**: error | **Dimension**: security | **AutoFix**: ✓

Assigning non-empty string literals to credential-like variables risks secret leakage.

Run `slopsentinel explain E09` for details and examples (when available).

#### E10 — Excessive guard clauses
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗

Too many consecutive guard clauses at the start of a function harms readability.

Run `slopsentinel explain E10` for details and examples (when available).

#### E11 — Redundant boolean return
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✓

Returning True/False from an if/else can be simplified to `return <condition>`.

**Bad**:
```python
if condition:
    return True
else:
    return False
```

**Good**:
```python
return condition
```

_Notes_: E11 flags redundant boolean returns that can be simplified.

#### E12 — Function too long
**Severity**: warn | **Dimension**: maintainability | **AutoFix**: ✗

Functions with very large bodies are hard to review and maintain.

Run `slopsentinel explain E12` for details and examples (when available).

### go

#### G01 — Symmetric create/delete pair unused (Go)
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗

AI-generated Go code often includes symmetric CRUD helpers even when unused.

Run `slopsentinel explain G01` for details and examples (when available).

#### G02 — Non-idiomatic error string (Go)
**Severity**: warn | **Dimension**: maintainability | **AutoFix**: ✗

Go error strings should not be capitalized or end with punctuation; AI-generated code often violates this convention.

**Bad**:
```go
return errors.New("Bad thing.")
```

**Good**:
```go
return errors.New("bad thing")
```

_Notes_: Idiomatic Go error strings are lowercase and punctuation-free.

#### G03 — Debug print statements (Go)
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗

Debug prints like fmt.Println("DEBUG...") are common AI scaffolding and should not ship to production.

**Bad**:
```go
fmt.Println("DEBUG: reached here")
```

**Good**:
```go
logger.Debug("reached here") // behind a debug flag
```

#### G04 — context.TODO() used (Go)
**Severity**: warn | **Dimension**: maintainability | **AutoFix**: ✗

context.TODO() is a placeholder that frequently slips into AI-generated code.

**Bad**:
```go
ctx := context.TODO()
```

**Good**:
```go
ctx := context.Background() // top-level only; prefer threading ctx in
```

#### G05 — time.Sleep used (Go)
**Severity**: info | **Dimension**: quality | **AutoFix**: ✗

time.Sleep in application code is often a flaky workaround used in AI-generated scaffolding.

**Bad**:
```go
time.Sleep(2 * time.Second)
```

**Good**:
```go
time.Sleep(backoff.Next()) // bounded + documented, or use sync primitives
```

#### G06 — Global variable mutation (Go)
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗

Mutating package-level variables is a common AI shortcut that introduces hidden state and potential races.

Run `slopsentinel explain G06` for details and examples (when available).

#### G07 — Repeated magic numbers (Go)
**Severity**: info | **Dimension**: maintainability | **AutoFix**: ✗

Repeated multi-digit numeric literals often indicate AI-generated scaffolding; prefer named constants.

Run `slopsentinel explain G07` for details and examples (when available).

### rust

#### R01 — Symmetric create/delete pair unused (Rust)
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗

AI-generated Rust code often includes symmetric CRUD helpers even when unused.

Run `slopsentinel explain R01` for details and examples (when available).

#### R02 — Excessive unwrap/expect (Rust)
**Severity**: warn | **Dimension**: security | **AutoFix**: ✗

Frequent `.unwrap()`/`.expect(...)` in non-test Rust code is a common AI shortcut that reduces robustness.

**Bad**:
```rust
let value = maybe_value.unwrap();
```

**Good**:
```rust
let value = maybe_value.ok_or(MyError::MissingValue)?;
```

#### R03 — todo!/unimplemented! macro used (Rust)
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗

`todo!()` and `unimplemented!()` are placeholders that should not ship.

**Bad**:
```rust
todo!("implement")
```

**Good**:
```rust
return Err(MyError::NotImplemented);
```

#### R04 — Debug macros (Rust)
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗

`dbg!` and println!-based debug logging often indicates AI scaffolding that should be removed or gated.

**Bad**:
```rust
dbg!(value);
```

**Good**:
```rust
tracing::debug!(?value);
```

#### R05 — unsafe used (Rust)
**Severity**: info | **Dimension**: security | **AutoFix**: ✗

Unnecessary `unsafe` in AI-generated code can introduce memory safety risks.

**Bad**:
```rust
unsafe { do_thing(ptr) }
```

**Good**:
```rust
do_thing_safe(&mut value) // prefer safe wrappers; document invariants if unsafe is required
```

#### R06 — Redundant clone on Copy-like values (Rust)
**Severity**: info | **Dimension**: maintainability | **AutoFix**: ✗

Cloning primitives/references is often an AI pattern; Copy types can be copied without `.clone()`.

Run `slopsentinel explain R06` for details and examples (when available).

#### R07 — panic! macro used (Rust)
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗

`panic!()` indicates unrecoverable failure; AI-generated code often leaves panics in production paths.

Run `slopsentinel explain R07` for details and examples (when available).

### java

#### J01 — Debug print statements (Java)
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗

System.out/err debug prints often indicate scaffolding that should be replaced with proper logging.

**Bad**:
```java
System.out.println("DEBUG");
```

**Good**:
```java
logger.debug("...");
```

#### J02 — Trivial null-returning method (Java)
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗

AI-generated Java code often includes stub methods that only `return null;`, leading to nullable APIs.

Run `slopsentinel explain J02` for details and examples (when available).

#### J03 — Empty catch block (Java)
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗

Empty `catch` blocks silently swallow failures; AI-generated code often includes them.

Run `slopsentinel explain J03` for details and examples (when available).

### kotlin

#### K01 — TODO() used (Kotlin)
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗

Kotlin's TODO() call is a placeholder that should not ship.

**Bad**:
```kotlin
TODO("implement")
```

**Good**:
```kotlin
throw NotImplementedError("implement")
```

_Notes_: Prefer explicit errors + tracking issues over TODO() placeholders in shipped code.

#### K02 — Non-null assertion used (Kotlin)
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗

Kotlin's `!!` is a common AI shortcut that can cause runtime crashes; prefer safe null handling.

Run `slopsentinel explain K02` for details and examples (when available).

#### K03 — Debug println (Kotlin)
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗

println("DEBUG...") statements often indicate AI scaffolding that should be removed or gated.

Run `slopsentinel explain K03` for details and examples (when available).

### ruby

#### Y01 — Debugger statements present (Ruby)
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗

Ruby debugger hooks like `binding.pry` frequently leak from AI-assisted development.

**Bad**:
```ruby
binding.pry
```

**Good**:
```ruby
# remove debugger hooks before commit
```

#### Y02 — Debug output via puts/p (Ruby)
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗

Debug output like `puts "DEBUG"` or `p "TODO"` is common AI scaffolding and should not ship.

Run `slopsentinel explain Y02` for details and examples (when available).

#### Y03 — raise RuntimeError (Ruby)
**Severity**: info | **Dimension**: maintainability | **AutoFix**: ✗

Raising RuntimeError explicitly is often an AI default; prefer a specific exception type with context.

Run `slopsentinel explain Y03` for details and examples (when available).

### php

#### P01 — Debug functions used (PHP)
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗

Debug helpers like var_dump/print_r are often left in AI-generated PHP code.

**Bad**:
```php
var_dump($x);
```

**Good**:
```php
error_log(print_r($x, true)); // behind env guard
```

#### P02 — die/exit used with message (PHP)
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗

Using die()/exit() with a string message is often AI scaffolding that abruptly terminates execution.

Run `slopsentinel explain P02` for details and examples (when available).

#### P03 — eval used (PHP)
**Severity**: warn | **Dimension**: security | **AutoFix**: ✗

eval() is a dangerous dynamic execution primitive; it frequently appears in AI-generated quick fixes.

Run `slopsentinel explain P03` for details and examples (when available).

### crossfile

#### X01 — Duplicate code across files
**Severity**: warn | **Dimension**: maintainability | **AutoFix**: ✗

Exact or near-exact copy/paste across multiple files often indicates AI scaffolding or cargo-cult duplication.

**Bad**:
```text
src/foo.py and src/bar.py contain identical code bodies.
```

**Good**:
```text
Extract shared code into a helper/module.
```

#### X02 — Inconsistent filename style
**Severity**: info | **Dimension**: maintainability | **AutoFix**: ✗

Mixed naming styles in the same directory/language can indicate AI-generated scaffolding and makes repos harder to navigate.

**Bad**:
```text
src/foo_bar.py, src/fooBar.py mixed in same directory.
```

**Good**:
```text
Pick one convention per directory/language (e.g. snake_case for Python).
```

#### X03 — Repeated Python file structure
**Severity**: warn | **Dimension**: fingerprint | **AutoFix**: ✗

Many Python files with identical structural skeletons can indicate AI-generated scaffolding across a repo.

**Bad**:
```text
Many Python files share the same structural skeleton (same function/class shapes, only names differ).
```

**Good**:
```text
Extract shared helpers or generate templates instead of duplicating scaffolds.
```

#### X04 — Circular imports under src/
**Severity**: warn | **Dimension**: quality | **AutoFix**: ✗

Circular imports between local Python modules under src/ are fragile and can cause import-time crashes.

Run `slopsentinel explain X04` for details and examples (when available).

#### X05 — Missing test file for src module
**Severity**: info | **Dimension**: maintainability | **AutoFix**: ✗

Modules under src/ without a corresponding tests/test_<module>.py file often indicate untested or scaffolded code.

Run `slopsentinel explain X05` for details and examples (when available).
