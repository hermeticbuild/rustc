extern crate proc_macro;

use proc_macro::{Literal, Span, TokenStream, TokenTree};
use std::cell::RefCell;
use std::sync::{Arc, atomic::{AtomicUsize, Ordering}};

struct MacroThreadState {
    values: Vec<u64>,
    drops: Arc<AtomicUsize>,
}

impl Drop for MacroThreadState {
    fn drop(&mut self) {
        assert_eq!(self.values.len(), 4096);
        self.drops.fetch_add(1, Ordering::SeqCst);
    }
}

thread_local! {
    static MACRO_TLS: RefCell<Option<MacroThreadState>> = const { RefCell::new(None) };
}

#[proc_macro]
pub fn exercise(input: TokenStream) -> TokenStream {
    assert_eq!(input.to_string(), "dynamic_std_input");
    assert_eq!(input.clone().to_string(), input.to_string());
    let mut tokens = input.into_iter();
    let token = tokens.next().expect("input token");
    assert!(tokens.next().is_none());
    let span = token.span().resolved_at(Span::call_site());
    assert!(span.line() > 0 && span.column() > 0);
    let file = span.file();
    assert!(file.ends_with("dynamic_std.rs"));
    let source_text = span.source_text();
    if let Some(text) = &source_text {
        assert_eq!(text, "dynamic_std_input");
    }

    // Match the allocation/thread/TLS/unwind exercise in validate_distribution.py
    // while this macro's Rust runtime comes from the shared libstd dependency.
    MACRO_TLS.with(|state| assert!(state.borrow().is_none()));
    let drops = Arc::new(AtomicUsize::new(0));
    let thread_drops = Arc::clone(&drops);
    let answer = std::thread::spawn(move || {
        MACRO_TLS.with(|state| {
            *state.borrow_mut() = Some(MacroThreadState {
                values: (0..4096).collect(),
                drops: thread_drops,
            });
        });
        MACRO_TLS.with(|state| {
            let state = state.borrow();
            assert_eq!(state.as_ref().unwrap().values.iter().sum::<u64>(), 4095 * 4096 / 2);
        });
        assert!(std::panic::catch_unwind(|| {
            panic!("expected dynamic libstd macro panic");
        }).is_err());
        42_u64
    }).join().expect("dynamic libstd macro thread join");
    assert_eq!(drops.load(Ordering::SeqCst), 1, "dynamic libstd macro TLS destructor");

    let loader_directory = std::env::var("LD_LIBRARY_PATH").expect("inherited loader environment");
    let mut literal = Literal::u64_suffixed(answer);
    literal.set_span(span);
    let answer_tokens: TokenStream = TokenTree::Literal(literal).into();
    println!("DYNAMIC_STD_RUNTIME_PASS tls_drops=1");
    format!(
        "({answer_tokens}, {loader_directory:?}, {}, {}, {}, {file:?})",
        source_text.is_some(), span.line(), span.column(),
    ).parse().unwrap()
}
