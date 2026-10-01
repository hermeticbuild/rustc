fn main() {
    assert_eq!(constructor_macros::constructor_value!(), 42);
    assert_eq!(constructor_macros::constructor_value!(), 42);
    println!("CASE_PASS constructor_tls");
}
