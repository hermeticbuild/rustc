use integration_macros::{decorate, round_trip, Describe};

#[derive(Describe)]
struct Record {
    value: u32,
}

#[decorate(7)]
fn attributed() -> u32 {
    35
}

fn main() {
    let value = round_trip!({
        let values: Vec<(u32, &'static str)> = vec![(40, "kept text"), (2, r#"raw text"#)];
        values.iter().map(|(number, _)| *number).sum::<u32>()
    });
    assert_eq!(value, 42);
    assert_eq!(Record { value: 40 }.derived_value(), 42);
    assert_eq!(attributed() + ATTRIBUTE_VALUE, 42);
    println!("CASE_PASS basic");
}
