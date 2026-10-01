fn main() {
    let result: (u64, &str, bool, usize, usize, &str) =
        dynamic_std_macros::exercise!(dynamic_std_input);
    assert_eq!(result.0, 42);
    let expected_loader_directory = std::env::args().nth(2).expect("expected loader directory");
    assert_eq!(result.1, expected_loader_directory);
    assert!(result.3 > 0 && result.4 > 0);
    assert!(result.5.ends_with("dynamic_std.rs"));
    println!("SOURCE_TEXT_AVAILABLE {}", result.2);
    println!("CASE_PASS dynamic_std");
}
