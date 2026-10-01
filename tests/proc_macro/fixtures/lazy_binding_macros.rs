extern crate proc_macro;

use proc_macro::TokenStream;

unsafe extern "C" {
    fn proc_macro_case_unresolved_native() -> u32;
}

#[proc_macro]
pub fn safe_value(_: TokenStream) -> TokenStream {
    "42u32".parse().unwrap()
}

// This exported macro remains in the declaration table, but the consumer never
// invokes it. Its native call must remain an unresolved PLT relocation.
#[proc_macro]
pub fn unused_native_call(_: TokenStream) -> TokenStream {
    let value = unsafe { proc_macro_case_unresolved_native() };
    value.to_string().parse().unwrap()
}
