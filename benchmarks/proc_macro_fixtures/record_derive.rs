//! Small, dependency-free binary-record derive used by the compiler benchmark.

extern crate proc_macro;

use proc_macro::{Delimiter, Ident, TokenStream, TokenTree};
use std::fmt::Write;

fn record_fields(input: TokenStream) -> (Ident, Vec<Ident>) {
    let mut tokens = input.into_iter();
    loop {
        match tokens.next() {
            Some(TokenTree::Ident(keyword)) if keyword.to_string() == "struct" => break,
            Some(_) => {}
            None => panic!("WireRecord requires a struct"),
        }
    }
    let name = match tokens.next() {
        Some(TokenTree::Ident(name)) => name,
        _ => panic!("WireRecord requires a struct name"),
    };
    let body = match tokens.next() {
        Some(TokenTree::Group(body)) if body.delimiter() == Delimiter::Brace => body,
        _ => panic!("WireRecord requires named fields and no generic parameters"),
    };
    assert!(tokens.next().is_none(), "unexpected tokens after the struct body");
    let mut fields = Vec::new();
    let mut field = body.stream().into_iter();
    while let Some(token) = field.next() {
        let name = match token {
            TokenTree::Ident(name) if name.to_string() == "pub" => match field.next() {
                Some(TokenTree::Ident(name)) => name,
                _ => panic!("WireRecord requires a named public field"),
            },
            TokenTree::Ident(name) => name,
            _ => panic!("WireRecord requires a named field"),
        };
        match field.next() {
            Some(TokenTree::Punct(colon)) if colon.as_char() == ':' => {}
            _ => panic!("WireRecord requires a field type"),
        }
        let mut type_tokens = 0;
        for token in field.by_ref() {
            if matches!(&token, TokenTree::Punct(comma) if comma.as_char() == ',') {
                break;
            }
            type_tokens += 1;
        }
        assert!(type_tokens > 0, "WireRecord requires a nonempty field type");
        fields.push(name);
    }
    assert!(!fields.is_empty(), "WireRecord requires at least one field");
    (name, fields)
}

#[proc_macro_derive(WireRecord)]
pub fn derive_wire_record(input: TokenStream) -> TokenStream {
    let (name, fields) = record_fields(input);
    let fields: Vec<_> = fields.iter().map(Ident::to_string).collect();
    let mut body = String::from("{ const FIELD_NAMES: &'static [&'static str] = &[");
    for field in &fields {
        write!(body, "{field:?},").unwrap();
    }
    body.push_str("]; fn encode(&self, output: &mut Vec<u8>) {");
    for field in &fields {
        write!(body, "WireField::encode(&self.{field}, output);").unwrap();
    }
    body.push_str("} fn checksum(&self) -> u64 { let mut state = 0xcbf29ce484222325_u64;");
    for field in &fields {
        write!(body, "state = state.rotate_left(7) ^ WireField::checksum(&self.{field});").unwrap();
    }
    body.push_str("state } }");
    let mut output: TokenStream = "impl WireRecord for".parse().unwrap();
    output.extend([TokenTree::Ident(name)]);
    output.extend(body.parse::<TokenStream>().unwrap());
    output
}
