fn main() {
    let (text, line, column, end_line, end_column, file, local_file, byte_length):
        (Option<&str>, usize, usize, usize, usize, &str, Option<&str>, usize) =
        integration_macros::source_details!(source_marker);
    assert!(line > 0 && column > 0);
    assert_eq!(end_line, line);
    assert_eq!(end_column - column, "source_marker".len());
    assert_eq!(byte_length, "source_marker".len());
    assert!(file.ends_with("spans.rs"));
    if let Some(local_file) = local_file {
        assert!(local_file.ends_with("spans.rs"));
        assert!(std::path::Path::new(local_file).is_file());
    }
    if let Some(text) = text {
        assert_eq!(text, "source_marker");
        println!("SOURCE_TEXT_AVAILABLE true");
    } else {
        println!("SOURCE_TEXT_AVAILABLE false");
    }
    println!("SPAN_FILE {file}");
    println!("CASE_PASS spans");
}
