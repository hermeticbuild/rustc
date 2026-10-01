extern crate proc_macro;

use proc_macro::TokenStream;
use std::cell::Cell;
use std::sync::atomic::{AtomicUsize, Ordering};

static CONSTRUCTOR_CALLS: AtomicUsize = AtomicUsize::new(0);
static CONSTRUCTOR_TLS_DROPS: AtomicUsize = AtomicUsize::new(0);

struct ConstructorState {
    initialized: Cell<bool>,
}

impl Drop for ConstructorState {
    fn drop(&mut self) {
        if self.initialized.get() {
            CONSTRUCTOR_TLS_DROPS.fetch_add(1, Ordering::SeqCst);
        }
    }
}

thread_local! {
    static CONSTRUCTOR_STATE: ConstructorState = const {
        ConstructorState { initialized: Cell::new(false) }
    };
}

extern "C" fn initialize_constructor_state() {
    CONSTRUCTOR_STATE.with(|state| state.initialized.set(true));
    CONSTRUCTOR_CALLS.fetch_add(1, Ordering::SeqCst);
}

#[used]
#[unsafe(link_section = ".init_array")]
static INITIALIZE_CONSTRUCTOR_STATE: extern "C" fn() = initialize_constructor_state;

#[proc_macro]
pub fn constructor_value(_: TokenStream) -> TokenStream {
    assert_eq!(CONSTRUCTOR_CALLS.load(Ordering::SeqCst), 1, "DSO constructor must execute once");
    assert_eq!(
        CONSTRUCTOR_TLS_DROPS.load(Ordering::SeqCst),
        0,
        "constructor TLS was destroyed before macro invocation",
    );
    assert!(
        CONSTRUCTOR_STATE.with(|state| state.initialized.get()),
        "constructor TLS is not available on the default macro thread",
    );
    "42u32".parse().unwrap()
}
