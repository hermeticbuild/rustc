fn main() {
    let expected_cwd = std::env::args().nth(1).expect("expected compiler working directory");
    let (value, cwd, contents) = integration_macros::observed_environment!();
    assert_eq!(value, "tracked-value-λ");
    assert_eq!(cwd, expected_cwd);
    assert_eq!(contents, "relative fixture contents\n");
    println!("CASE_PASS environment");
}
