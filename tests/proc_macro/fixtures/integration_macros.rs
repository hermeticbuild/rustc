#![feature(proc_macro_expand, proc_macro_quote, proc_macro_span, proc_macro_tracked_env, proc_macro_tracked_path)]

extern crate proc_macro;

use proc_macro::{Literal, Span, TokenStream, TokenTree};
use std::sync::atomic::{AtomicUsize, Ordering};

static NEXT_SEQUENCE: AtomicUsize = AtomicUsize::new(0);

fn string_literal(value: &str) -> TokenStream {
    TokenTree::Literal(Literal::string(value)).into()
}

#[proc_macro]
pub fn round_trip(input: TokenStream) -> TokenStream {
    fn copy_tokens(input: TokenStream) -> TokenStream {
        input
            .into_iter()
            .map(|token| match token {
                TokenTree::Group(group) => {
                    let mut copy = proc_macro::Group::new(group.delimiter(), copy_tokens(group.stream()));
                    copy.set_span(group.span());
                    TokenTree::Group(copy)
                }
                mut token => {
                    token.set_span(token.span().resolved_at(Span::call_site()));
                    token
                }
            })
            .collect()
    }
    copy_tokens(input.clone())
}

#[proc_macro_derive(Describe)]
pub fn describe(input: TokenStream) -> TokenStream {
    let mut after_struct = false;
    for token in input {
        if let TokenTree::Ident(ident) = token {
            if after_struct {
                return format!(
                    "impl {ident} {{ pub fn derived_value(&self) -> u32 {{ self.value + 2 }} }}"
                )
                .parse()
                .unwrap();
            }
            after_struct = ident.to_string() == "struct";
        }
    }
    panic!("Describe expects a struct");
}

#[proc_macro_attribute]
pub fn decorate(arguments: TokenStream, input: TokenStream) -> TokenStream {
    assert_eq!(arguments.to_string(), "7");
    let mut output = input.clone();
    output.extend("const ATTRIBUTE_VALUE: u32 = 7;".parse::<TokenStream>().unwrap());
    output
}

#[proc_macro]
pub fn sequence(_: TokenStream) -> TokenStream {
    NEXT_SEQUENCE.fetch_add(1, Ordering::SeqCst).to_string().parse().unwrap()
}

#[proc_macro]
pub fn nested_literal(_: TokenStream) -> TokenStream {
    string_literal("nested-proc-macro")
}

#[proc_macro]
pub fn expand_literal(input: TokenStream) -> TokenStream {
    input.expand_expr().expect("literal expansion must succeed")
}

#[proc_macro]
pub fn source_details(input: TokenStream) -> TokenStream {
    let mut tokens = input.into_iter();
    let token = tokens.next().expect("one source token");
    assert!(tokens.next().is_none());
    let span = token.span();
    let bytes = span.byte_range();
    // source_text is diagnostic, best-effort information. The consumer records
    // availability, and checks its contents only when source_text is present.
    format!(
        "({:?}, {}, {}, {}, {}, {:?}, {:?}, {})",
        span.source_text(),
        span.line(),
        span.column(),
        span.end().line(),
        span.end().column(),
        span.file(),
        span.local_file().map(|path| path.to_string_lossy().into_owned()),
        bytes.end - bytes.start,
    )
    .parse()
    .unwrap()
}

#[proc_macro]
pub fn observed_environment(_: TokenStream) -> TokenStream {
    let value = proc_macro::tracked::env_var("PROC_MACRO_CASE_TRACKED")
        .expect("tracked test environment variable");
    assert!(proc_macro::tracked::env_var("PROC_MACRO_CASE_MISSING").is_err());
    proc_macro::tracked::path("fixture-input.txt");
    let contents = std::fs::read_to_string("fixture-input.txt").expect("relative fixture input");
    let cwd = std::env::current_dir().expect("compiler working directory");
    format!("({value:?}, {:?}, {contents:?})", cwd.to_string_lossy())
        .parse()
        .unwrap()
}

#[proc_macro]
pub fn noisy(_: TokenStream) -> TokenStream {
    println!("PROC_MACRO_CASE_STDOUT {{\"macro\":\"stdout\"}}");
    eprintln!("PROC_MACRO_CASE_STDERR {{\"macro\":\"stderr\"}}");
    "42u32".parse().unwrap()
}

#[proc_macro]
pub fn quoted_value(input: TokenStream) -> TokenStream {
    proc_macro::quote!({
        let value: u32 = $input;
        value + 2
    })
}

#[proc_macro]
pub fn panic_bang(_: TokenStream) -> TokenStream {
    panic!("PROC_MACRO_CASE_BANG_PANIC");
}

#[proc_macro_attribute]
pub fn panic_attribute(_: TokenStream, _: TokenStream) -> TokenStream {
    panic!("PROC_MACRO_CASE_ATTRIBUTE_PANIC");
}

#[proc_macro_derive(PanicDerive)]
pub fn panic_derive(_: TokenStream) -> TokenStream {
    panic!("PROC_MACRO_CASE_DERIVE_PANIC");
}
