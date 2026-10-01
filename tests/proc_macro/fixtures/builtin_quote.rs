fn main() {
    assert_eq!(integration_macros::quoted_value!(40), 42);
    println!("CASE_PASS builtin_quote");
}
