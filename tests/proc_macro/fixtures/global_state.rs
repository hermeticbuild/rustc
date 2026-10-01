use integration_macros::sequence;

const FIRST: usize = sequence!();

mod another_module {
    pub const SECOND: usize = integration_macros::sequence!();
}

fn main() {
    // Macro expansion order is deliberately not assumed. This is a compiler
    // compatibility observation, not a Rust language guarantee about globals.
    let mut values = [FIRST, another_module::SECOND, sequence!(), sequence!(), sequence!(), sequence!()];
    values.sort_unstable();
    assert_eq!(values, [0, 1, 2, 3, 4, 5]);
    println!("CASE_PASS global_state values={values:?}");
}
