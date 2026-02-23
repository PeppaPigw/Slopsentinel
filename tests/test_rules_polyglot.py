from __future__ import annotations

from helpers import make_file_ctx

from slopsentinel.rules.polyglot import (
    G01GoSymmetricCreateDeleteUnused,
    G02GoNonIdiomaticErrorString,
    G03GoDebugPrintStatements,
    G04GoContextTodoUsed,
    G05GoTimeSleepUsed,
    J01JavaDebugPrintStatements,
    K01KotlinTodoUsed,
    P01PhpDebugFunctions,
    R01RustSymmetricCreateDeleteUnused,
    R02RustExcessiveUnwrapExpect,
    R03RustTodoMacros,
    R04RustDebugMacros,
    R05RustUnsafeUsed,
    Y01RubyDebuggersPresent,
)


def test_g01_go_symmetric_pair_unused(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=(
            "package main\n\n"
            "func CreateUser() {}\n"
            "func DeleteUser() {}\n"
            "func main() {}\n"
        ),
    )
    violations = G01GoSymmetricCreateDeleteUnused().check_file(ctx)
    assert any(v.rule_id == "G01" for v in violations)


def test_g01_go_symmetric_pair_used_is_not_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=(
            "package main\n\n"
            "func CreateUser() {}\n"
            "func DeleteUser() {}\n"
            "func main() { CreateUser() }\n"
        ),
    )
    violations = G01GoSymmetricCreateDeleteUnused().check_file(ctx)
    assert not violations


def test_r01_rust_symmetric_pair_unused(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.rs",
        content=(
            "fn create_user() {}\n"
            "fn delete_user() {}\n"
            "fn main() {}\n"
        ),
    )
    violations = R01RustSymmetricCreateDeleteUnused().check_file(ctx)
    assert any(v.rule_id == "R01" for v in violations)


def test_r01_rust_trait_declarations_are_ignored(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.rs",
        content=(
            "trait Store {\n"
            "    fn create_user(&self);\n"
            "    fn delete_user(&self);\n"
            "}\n"
        ),
    )
    violations = R01RustSymmetricCreateDeleteUnused().check_file(ctx)
    assert not violations


def test_g02_go_non_idiomatic_error_string(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=("package main\n\n" 'func f() error { return errors.New("Bad thing.") }\n'),
    )
    violations = G02GoNonIdiomaticErrorString().check_file(ctx)
    assert any(v.rule_id == "G02" for v in violations)


def test_g02_go_idiomatic_error_string_not_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=("package main\n\n" 'func f() error { return errors.New("bad thing") }\n'),
    )
    violations = G02GoNonIdiomaticErrorString().check_file(ctx)
    assert not violations


def test_g03_go_debug_print_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=("package main\n\n" 'func main() { fmt.Println("DEBUG: hi") }\n'),
    )
    violations = G03GoDebugPrintStatements().check_file(ctx)
    assert any(v.rule_id == "G03" for v in violations)


def test_g04_go_context_todo_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=("package main\n\n" "func main() { _ = context.TODO() }\n"),
    )
    violations = G04GoContextTodoUsed().check_file(ctx)
    assert any(v.rule_id == "G04" for v in violations)


def test_g05_go_time_sleep_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.go",
        content=("package main\n\n" "func main() { time.Sleep(1) }\n"),
    )
    violations = G05GoTimeSleepUsed().check_file(ctx)
    assert any(v.rule_id == "G05" for v in violations)


def test_r02_rust_excessive_unwrap_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.rs",
        content=(
            "fn f() {\n"
            "    let _ = Some(1).unwrap();\n"
            "    let _ = Some(2).unwrap();\n"
            "    let _ = Some(3).unwrap();\n"
            "}\n"
        ),
    )
    violations = R02RustExcessiveUnwrapExpect().check_file(ctx)
    assert any(v.rule_id == "R02" for v in violations)


def test_r03_rust_todo_macro_flagged(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.rs", content='fn f() { todo!("later"); }\n')
    violations = R03RustTodoMacros().check_file(ctx)
    assert any(v.rule_id == "R03" for v in violations)


def test_r04_rust_dbg_macro_flagged(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.rs", content="fn f() { dbg!(1); }\n")
    violations = R04RustDebugMacros().check_file(ctx)
    assert any(v.rule_id == "R04" for v in violations)


def test_r05_rust_unsafe_flagged(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.rs", content="unsafe fn f() {}\n")
    violations = R05RustUnsafeUsed().check_file(ctx)
    assert any(v.rule_id == "R05" for v in violations)


def test_j01_java_debug_print_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/Example.java",
        content='class Example { void f() { System.out.println("DEBUG"); } }\n',
    )
    violations = J01JavaDebugPrintStatements().check_file(ctx)
    assert any(v.rule_id == "J01" for v in violations)


def test_k01_kotlin_todo_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/Example.kt",
        content='fun f() { TODO("implement") }\n',
    )
    violations = K01KotlinTodoUsed().check_file(ctx)
    assert any(v.rule_id == "K01" for v in violations)


def test_y01_ruby_debugger_flagged(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.rb", content="binding.pry\n")
    violations = Y01RubyDebuggersPresent().check_file(ctx)
    assert any(v.rule_id == "Y01" for v in violations)


def test_p01_php_debug_function_flagged(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.php", content="<?php var_dump($x); ?>\n")
    violations = P01PhpDebugFunctions().check_file(ctx)
    assert any(v.rule_id == "P01" for v in violations)
