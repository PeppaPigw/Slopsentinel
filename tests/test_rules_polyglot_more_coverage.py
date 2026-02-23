from __future__ import annotations

from helpers import make_file_ctx

from slopsentinel.rules import polyglot as poly
from slopsentinel.rules.polyglot import (
    G01GoSymmetricCreateDeleteUnused,
    G02GoNonIdiomaticErrorString,
    G03GoDebugPrintStatements,
    G04GoContextTodoUsed,
    G05GoTimeSleepUsed,
    G06GoGlobalVarMutation,
    G07GoMagicNumbers,
    J01JavaDebugPrintStatements,
    J02JavaNullableReturnHeuristic,
    J03JavaEmptyCatchBlock,
    K01KotlinTodoUsed,
    K02KotlinNonNullAssertionUsed,
    K03KotlinPrintlnDebug,
    P01PhpDebugFunctions,
    P02PhpDieExitUsed,
    P03PhpEvalUsed,
    R01RustSymmetricCreateDeleteUnused,
    R02RustExcessiveUnwrapExpect,
    R03RustTodoMacros,
    R04RustDebugMacros,
    R05RustUnsafeUsed,
    R06RustCloneOnCopyTypes,
    R07RustPanicMacroUsed,
    Y01RubyDebuggersPresent,
    Y02RubyDebugOutput,
    Y03RubyRaiseRuntimeError,
)


def test_pair_create_delete_supports_add_remove_pairs_in_rust(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.rs",
        content=(
            "fn add_user() {}\n"
            "fn remove_user() {}\n"
            "fn main() {}\n"
        ),
    )
    violations = R01RustSymmetricCreateDeleteUnused().check_file(ctx)
    assert any(v.rule_id == "R01" for v in violations)


def test_pair_create_delete_supports_add_remove_pairs_in_go(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=(
            "package main\n\n"
            "func AddUser() {}\n"
            "func RemoveUser() {}\n"
            "func main() {}\n"
        ),
    )
    violations = G01GoSymmetricCreateDeleteUnused().check_file(ctx)
    assert any(v.rule_id == "G01" for v in violations)


def test_unused_symmetric_pairs_skips_missing_counterpart(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.rs",
        content=(
            "fn create_user() {}\n"
            "fn main() {}\n"
        ),
    )
    assert not R01RustSymmetricCreateDeleteUnused().check_file(ctx)


def test_is_rust_test_file_recognizes_test_suffix(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example_test.rs",
        content='fn f() { panic!("nope"); }\n',
    )
    assert not R07RustPanicMacroUsed().check_file(ctx)


def test_kotlin_nonnull_assertion_ignores_triple_quoted_strings_and_comments(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/Example.kt",
        content=(
            'val s = """\n'
            "inside string !! should not trigger\n"
            '"""\n'
            "// !! in comment should not trigger\n"
            "/*\n"
            "!! in block comment should not trigger\n"
            "*/\n"
            'println("!!")\n'
        ),
    )
    assert not K02KotlinNonNullAssertionUsed().check_file(ctx)


def test_blank_out_kotlin_strings_tracks_triple_quote_state() -> None:
    line, in_triple = poly._blank_out_kotlin_strings('val s = """', in_triple=False)
    assert in_triple is True
    assert '"""' not in line

    line2, in_triple2 = poly._blank_out_kotlin_strings("hello !!", in_triple=in_triple)
    assert in_triple2 is True
    assert "!!" not in line2

    line3, in_triple3 = poly._blank_out_kotlin_strings('"""', in_triple=in_triple2)
    assert in_triple3 is False
    assert '"""' not in line3


def test_go_package_level_var_names_handles_var_blocks_and_skips_function_locals(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=(
            "package main\n\n"
            "var (\n"
            "    counter int\n"
            "    a, b int\n"
            ")\n"
            "var top int\n\n"
            "func Inline() { var local int }\n\n"
            "func Pending()\n"
            "{\n"
            "    var (\n"
            "        inner int\n"
            "    )\n"
            "    top = 1\n"
            "}\n"
        ),
    )

    names = poly._go_package_level_var_names(ctx)
    assert {"counter", "a", "b", "top"}.issubset(names)
    assert "local" not in names
    assert "inner" not in names


def test_go_first_global_mutation_returns_none_for_empty_globals(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.go", content="package main\n\nfunc f() {}\n")
    assert poly._go_first_global_mutation(ctx, global_vars=set()) is None


def test_go_first_global_mutation_detects_multi_line_assignments(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=(
            "package main\n\n"
            "var counter int\n\n"
            "func inc() {\n"
            "    counter = 2\n"
            "}\n"
        ),
    )
    global_vars = poly._go_package_level_var_names(ctx)
    hit = poly._go_first_global_mutation(ctx, global_vars=global_vars)
    assert hit is not None
    line_no, name = hit
    assert name == "counter"
    assert line_no == 6


def test_go_first_global_mutation_respects_local_var_declarations(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=(
            "package main\n\n"
            "var counter int\n\n"
            "func inc() {\n"
            "    var counter int\n"
            "    counter = 2\n"
            "}\n"
        ),
    )
    global_vars = poly._go_package_level_var_names(ctx)
    assert poly._go_first_global_mutation(ctx, global_vars=global_vars) is None


def test_go_first_global_mutation_detects_compound_assign_and_multi_lhs(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=(
            "package main\n\n"
            "var a, b int\n\n"
            "func f() {\n"
            "    a += 1\n"
            "}\n"
            "func g() {\n"
            "    a, b = 1, 2\n"
            "}\n"
        ),
    )
    global_vars = poly._go_package_level_var_names(ctx)
    hit = poly._go_first_global_mutation(ctx, global_vars=global_vars)
    assert hit is not None
    _line_no, name = hit
    assert name in {"a", "b"}


def test_go_first_global_mutation_parses_local_var_blocks(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=(
            "package main\n\n"
            "var counter int\n"
            "var other int\n\n"
            "func f() {\n"
            "    var (\n"
            "        counter int\n"
            "    )\n"
            "    counter = 2\n"
            "    other = 1\n"
            "}\n"
        ),
    )
    global_vars = poly._go_package_level_var_names(ctx)
    hit = poly._go_first_global_mutation(ctx, global_vars=global_vars)
    assert hit is not None
    _line_no, name = hit
    assert name == "other"


def test_go_first_global_mutation_handles_one_line_functions_without_mutations(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=(
            "package main\n\n"
            "var counter int\n\n"
            "func noop() {}\n"
            "func f() { counter := 1 }\n"
        ),
    )
    global_vars = poly._go_package_level_var_names(ctx)
    assert poly._go_first_global_mutation(ctx, global_vars=global_vars) is None


def test_g02_go_non_idiomatic_error_string_handles_empty_and_format_strings(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=(
            "package main\n\n"
            'func f() error { return errors.New("   ") }\n'
            'func g() error { return fmt.Errorf("%s", x) }\n'
        ),
    )
    assert not G02GoNonIdiomaticErrorString().check_file(ctx)


def test_go_debug_context_and_sleep_rules_cover_skip_and_no_match(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=(
            "package main\n\n"
            'func f() { fmt.Println("hello") }\n'
            "func g() { _ = context.Background() }\n"
            "func h() { _ = time.Now() }\n"
        ),
    )
    assert not G03GoDebugPrintStatements().check_file(ctx)
    assert not G04GoContextTodoUsed().check_file(ctx)
    assert not G05GoTimeSleepUsed().check_file(ctx)

    test_ctx = make_file_ctx(
        project_ctx,
        relpath="src/example_test.go",
        content=(
            "package main\n\n"
            'func f() { fmt.Println("DEBUG: hi") }\n'
            "func g() { _ = context.TODO() }\n"
            "func h() { time.Sleep(1) }\n"
        ),
    )
    assert not G03GoDebugPrintStatements().check_file(test_ctx)
    assert not G04GoContextTodoUsed().check_file(test_ctx)
    assert not G05GoTimeSleepUsed().check_file(test_ctx)


def test_g06_and_g07_skip_test_files_and_handle_const_blocks(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=(
            "package main\n\n"
            "const (\n"
            "  Answer = 42\n"
            "  Timeout = 3600\n"
            ")\n"
            "func f() { _ = Timeout; _ = Timeout; _ = Timeout; _ = Timeout }\n"
        ),
    )
    assert not G07GoMagicNumbers().check_file(ctx)

    test_ctx = make_file_ctx(
        project_ctx,
        relpath="src/example_test.go",
        content=(
            "package main\n\n"
            "var counter int\n"
            "func f() { counter = 1 }\n"
            "func g() { _ = 3600; _ = 3600; _ = 3600; _ = 3600 }\n"
        ),
    )
    assert not G06GoGlobalVarMutation().check_file(test_ctx)
    assert not G07GoMagicNumbers().check_file(test_ctx)


def test_rust_rules_cover_skip_and_negative_paths(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.rs", content="fn f() { let x = 1; }\n")
    assert not R02RustExcessiveUnwrapExpect().check_file(ctx)
    assert not R03RustTodoMacros().check_file(ctx)
    assert not R04RustDebugMacros().check_file(ctx)
    assert not R05RustUnsafeUsed().check_file(ctx)
    assert not R06RustCloneOnCopyTypes().check_file(ctx)
    assert not R07RustPanicMacroUsed().check_file(ctx)

    test_ctx = make_file_ctx(
        project_ctx,
        relpath="tests/example.rs",
        content="fn f() { dbg!(1); println!(\"DEBUG: hi\"); todo!(\"x\"); panic!(\"no\"); }\n",
    )
    assert not R02RustExcessiveUnwrapExpect().check_file(test_ctx)
    assert not R04RustDebugMacros().check_file(test_ctx)
    assert not R06RustCloneOnCopyTypes().check_file(test_ctx)
    assert not R07RustPanicMacroUsed().check_file(test_ctx)


def test_r04_rust_debug_macros_detects_println_debug(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.rs",
        content='fn f() { println!("DEBUG: hi"); }\n',
    )
    violations = R04RustDebugMacros().check_file(ctx)
    assert any(v.rule_id == "R04" for v in violations)


def test_java_rules_cover_negative_and_edge_paths(project_ctx) -> None:
    no_debug = make_file_ctx(project_ctx, relpath="src/Example.java", content="class Example { void f() {} }\n")
    assert not J01JavaDebugPrintStatements().check_file(no_debug)

    annotated = make_file_ctx(
        project_ctx,
        relpath="src/Example.java",
        content=(
            "import javax.annotation.Nullable;\n"
            "class Example { @Nullable String f() { return null; } }\n"
        ),
    )
    assert not J02JavaNullableReturnHeuristic().check_file(annotated)

    not_null = make_file_ctx(
        project_ctx,
        relpath="src/Example.java",
        content="class Example { int f() { return 1; } }\n",
    )
    assert not J02JavaNullableReturnHeuristic().check_file(not_null)

    multi_line_stub = make_file_ctx(
        project_ctx,
        relpath="src/Example.java",
        content=(
            "class Example {\n"
            "  String f() {\n"
            "    // comment\n"
            "    return null;\n"
            "  }\n"
            "}\n"
        ),
    )
    violations = J02JavaNullableReturnHeuristic().check_file(multi_line_stub)
    assert any(v.rule_id == "J02" for v in violations)

    empty_catch_todo = make_file_ctx(
        project_ctx,
        relpath="src/Example.java",
        content="class Example { void f() { try { g(); } catch (Exception e) { // TODO } } void g() {} }\n",
    )
    assert any(v.rule_id == "J03" for v in J03JavaEmptyCatchBlock().check_file(empty_catch_todo))

    empty_catch_multiline = make_file_ctx(
        project_ctx,
        relpath="src/Example.java",
        content=(
            "class Example {\n"
            "  void f() {\n"
            "    try { g(); } catch (Exception e) {\n"
            "    }\n"
            "  }\n"
            "  void g() {}\n"
            "}\n"
        ),
    )
    assert any(v.rule_id == "J03" for v in J03JavaEmptyCatchBlock().check_file(empty_catch_multiline))

    test_file = make_file_ctx(
        project_ctx,
        relpath="src/ExampleTest.java",
        content="class ExampleTest { void f() { try { g(); } catch (Exception e) { } } void g() {} }\n",
    )
    assert not J03JavaEmptyCatchBlock().check_file(test_file)


def test_kotlin_rules_cover_negative_paths(project_ctx) -> None:
    no_todo = make_file_ctx(
        project_ctx,
        relpath="src/Example.kt",
        content=(
            "fun f() {\n"
            "  val x = 1\n"
            '  println("hi")\n'
            "}\n"
        ),
    )
    assert not K01KotlinTodoUsed().check_file(no_todo)
    assert not K03KotlinPrintlnDebug().check_file(no_todo)

    test_file = make_file_ctx(
        project_ctx,
        relpath="src/ExampleTest.kt",
        content='fun f() { println("DEBUG: hi"); val x = foo!! }\n',
    )
    assert not K02KotlinNonNullAssertionUsed().check_file(test_file)
    assert not K03KotlinPrintlnDebug().check_file(test_file)


def test_ruby_rules_cover_negative_paths(project_ctx) -> None:
    no_debugger = make_file_ctx(project_ctx, relpath="src/example.rb", content="def f; end\n")
    assert not Y01RubyDebuggersPresent().check_file(no_debugger)

    no_debug_puts = make_file_ctx(project_ctx, relpath="src/example.rb", content='puts "hello"\n')
    assert not Y02RubyDebugOutput().check_file(no_debug_puts)

    no_match_line = make_file_ctx(project_ctx, relpath="src/example.rb", content="log.debug('DEBUG: hi')\n")
    assert not Y02RubyDebugOutput().check_file(no_match_line)

    test_file = make_file_ctx(project_ctx, relpath="test/test_example.rb", content='raise RuntimeError, "boom"\n')
    assert not Y03RubyRaiseRuntimeError().check_file(test_file)


def test_php_rules_cover_skip_and_negative_paths(project_ctx) -> None:
    no_debug = make_file_ctx(project_ctx, relpath="src/example.php", content="<?php $x = 1; ?>\n")
    assert not P01PhpDebugFunctions().check_file(no_debug)

    exit_zero = make_file_ctx(project_ctx, relpath="src/example.php", content="<?php exit(0); ?>\n")
    assert any(v.rule_id == "P02" for v in P02PhpDieExitUsed().check_file(exit_zero))

    in_tests = make_file_ctx(project_ctx, relpath="tests/ExampleTest.php", content="<?php eval($code); ?>\n")
    assert not P03PhpEvalUsed().check_file(in_tests)

    no_eval = make_file_ctx(project_ctx, relpath="src/example.php", content="<?php $x = 1; ?>\n")
    assert not P03PhpEvalUsed().check_file(no_eval)
