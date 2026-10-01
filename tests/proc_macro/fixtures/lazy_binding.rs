fn main() {
    assert_eq!(lazy_binding_macros::safe_value!(), 42);
    println!("CASE_PASS lazy_binding");
}
