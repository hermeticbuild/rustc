#[derive(integration_macros::Describe)]
struct Record {
    value: u32,
}

const INPUT_VALUE: u32 = 40;

fn main() {
    let expected: u32 = std::env::args().nth(2).expect("expected result").parse().unwrap();
    assert_eq!(Record { value: INPUT_VALUE }.derived_value(), expected);
    println!("CASE_PASS incremental_derive expected={expected}");
}
