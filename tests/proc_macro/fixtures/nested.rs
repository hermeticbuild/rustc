use integration_macros::expand_literal;

const ONCE: &str = expand_literal!(integration_macros::nested_literal!());
const TWICE: &str = expand_literal!(integration_macros::expand_literal!(
    integration_macros::nested_literal!()
));
const BUILTIN: &str = expand_literal!(concat!("nested", "-builtin"));

fn main() {
    assert_eq!(ONCE, "nested-proc-macro");
    assert_eq!(TWICE, "nested-proc-macro");
    assert_eq!(BUILTIN, "nested-builtin");
    println!("CASE_PASS nested");
}
