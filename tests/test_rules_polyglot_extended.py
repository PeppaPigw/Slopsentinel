from __future__ import annotations

from helpers import make_file_ctx

from slopsentinel.rules.polyglot import (
    G06GoGlobalVarMutation,
    G07GoMagicNumbers,
    J02JavaNullableReturnHeuristic,
    J03JavaEmptyCatchBlock,
    K02KotlinNonNullAssertionUsed,
    K03KotlinPrintlnDebug,
    P02PhpDieExitUsed,
    P03PhpEvalUsed,
    R06RustCloneOnCopyTypes,
    R07RustPanicMacroUsed,
    Y02RubyDebugOutput,
    Y03RubyRaiseRuntimeError,
)


def test_g06_go_global_var_mutation_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=(
            "package main\n\n"
            "var counter int\n\n"
            "func inc() { counter++ }\n"
        ),
    )
    violations = G06GoGlobalVarMutation().check_file(ctx)
    assert any(v.rule_id == "G06" for v in violations)


def test_g06_go_global_var_mutation_shadowed_not_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=(
            "package main\n\n"
            "var counter int\n\n"
            "func inc() {\n"
            "    counter := 0\n"
            "    counter++\n"
            "}\n"
        ),
    )
    violations = G06GoGlobalVarMutation().check_file(ctx)
    assert not violations


def test_g07_go_magic_numbers_repeated_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=(
            "package main\n\n"
            "func f(x int) bool {\n"
            "    if x == 42 { return true }\n"
            "    if x > 42 { return false }\n"
            "    if x < 42 { return false }\n"
            "    return x != 42\n"
            "}\n"
        ),
    )
    violations = G07GoMagicNumbers().check_file(ctx)
    assert any(v.rule_id == "G07" for v in violations)


def test_g07_go_magic_numbers_in_const_not_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=(
            "package main\n\n"
            "const Answer = 42\n\n"
            "func f(x int) bool {\n"
            "    if x == Answer { return true }\n"
            "    if x > Answer { return false }\n"
            "    if x < Answer { return false }\n"
            "    return x != Answer\n"
            "}\n"
        ),
    )
    violations = G07GoMagicNumbers().check_file(ctx)
    assert not violations


def test_j02_java_trivial_null_return_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/Example.java",
        content="class Example { String f() { return null; } }\n",
    )
    violations = J02JavaNullableReturnHeuristic().check_file(ctx)
    assert any(v.rule_id == "J02" for v in violations)


def test_j02_java_trivial_null_return_in_test_file_not_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/ExampleTest.java",
        content="class ExampleTest { String f() { return null; } }\n",
    )
    violations = J02JavaNullableReturnHeuristic().check_file(ctx)
    assert not violations


def test_j03_java_empty_catch_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/Example.java",
        content=(
            "class Example {\n"
            "  void f() {\n"
            "    try { g(); } catch (Exception e) { }\n"
            "  }\n"
            "  void g() {}\n"
            "}\n"
        ),
    )
    violations = J03JavaEmptyCatchBlock().check_file(ctx)
    assert any(v.rule_id == "J03" for v in violations)


def test_j03_java_non_empty_catch_not_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/Example.java",
        content=(
            "class Example {\n"
            "  void f() {\n"
            "    try { g(); } catch (Exception e) { System.err.println(e); }\n"
            "  }\n"
            "  void g() {}\n"
            "}\n"
        ),
    )
    violations = J03JavaEmptyCatchBlock().check_file(ctx)
    assert not violations


def test_k02_kotlin_non_null_assertion_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/Example.kt",
        content="fun f(x: String?) { val y = x!! }\n",
    )
    violations = K02KotlinNonNullAssertionUsed().check_file(ctx)
    assert any(v.rule_id == "K02" for v in violations)


def test_k02_kotlin_non_null_assertion_in_test_file_not_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/ExampleTest.kt",
        content="fun f(x: String?) { val y = x!! }\n",
    )
    violations = K02KotlinNonNullAssertionUsed().check_file(ctx)
    assert not violations


def test_k02_kotlin_exclamations_in_string_not_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/Example.kt",
        content='fun f() { println("!!") }\n',
    )
    violations = K02KotlinNonNullAssertionUsed().check_file(ctx)
    assert not violations


def test_k03_kotlin_debug_println_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/Example.kt",
        content='fun f() { println("DEBUG: hi") }\n',
    )
    violations = K03KotlinPrintlnDebug().check_file(ctx)
    assert any(v.rule_id == "K03" for v in violations)


def test_k03_kotlin_normal_println_not_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/Example.kt",
        content='fun f() { println("hello") }\n',
    )
    violations = K03KotlinPrintlnDebug().check_file(ctx)
    assert not violations


def test_y02_ruby_debug_puts_flagged(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.rb", content='puts "DEBUG: hi"\n')
    violations = Y02RubyDebugOutput().check_file(ctx)
    assert any(v.rule_id == "Y02" for v in violations)


def test_y02_ruby_debug_puts_in_spec_not_flagged(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="spec/example_spec.rb", content='puts "DEBUG: hi"\n')
    violations = Y02RubyDebugOutput().check_file(ctx)
    assert not violations


def test_y03_ruby_raise_runtime_error_flagged(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.rb", content='raise RuntimeError, "boom"\n')
    violations = Y03RubyRaiseRuntimeError().check_file(ctx)
    assert any(v.rule_id == "Y03" for v in violations)


def test_y03_ruby_raise_string_not_flagged(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.rb", content='raise "boom"\n')
    violations = Y03RubyRaiseRuntimeError().check_file(ctx)
    assert not violations


def test_p02_php_die_with_message_flagged(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.php", content='<?php die("DEBUG"); ?>\n')
    violations = P02PhpDieExitUsed().check_file(ctx)
    assert any(v.rule_id == "P02" for v in violations)


def test_p02_php_exit_with_code_not_flagged(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.php", content="<?php exit(1); ?>\n")
    violations = P02PhpDieExitUsed().check_file(ctx)
    assert not violations


def test_p02_php_die_in_test_file_not_flagged(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="tests/ExampleTest.php", content='<?php die("DEBUG"); ?>\n')
    violations = P02PhpDieExitUsed().check_file(ctx)
    assert not violations


def test_p03_php_eval_flagged(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.php", content="<?php eval($code); ?>\n")
    violations = P03PhpEvalUsed().check_file(ctx)
    assert any(v.rule_id == "P03" for v in violations)


def test_r06_rust_clone_on_bool_flagged(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.rs", content="fn f() { let _ = true.clone(); }\n")
    violations = R06RustCloneOnCopyTypes().check_file(ctx)
    assert any(v.rule_id == "R06" for v in violations)


def test_r06_rust_clone_on_non_copy_not_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.rs",
        content="fn f() { let v = vec![1, 2, 3]; let _ = v.clone(); }\n",
    )
    violations = R06RustCloneOnCopyTypes().check_file(ctx)
    assert not violations


def test_r07_rust_panic_flagged(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.rs", content='fn f() { panic!("nope"); }\n')
    violations = R07RustPanicMacroUsed().check_file(ctx)
    assert any(v.rule_id == "R07" for v in violations)


def test_r07_rust_panic_in_tests_dir_not_flagged(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="tests/example.rs", content='fn f() { panic!("nope"); }\n')
    violations = R07RustPanicMacroUsed().check_file(ctx)
    assert not violations
