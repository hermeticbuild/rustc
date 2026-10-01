//! Generic iterator and const-generic compilation workload. No external crates.

use std::fmt::Debug;
use std::ops::{Add, Mul, Sub};

trait Scalar: Copy + Debug + PartialOrd + Add<Output = Self> + Mul<Output = Self> + Sub<Output = Self> {
    fn from_u64(value: u64) -> Self;
    fn to_u64(self) -> u64;
}

macro_rules! scalars {
    ($($kind:ty),* $(,)?) => {
        $(impl Scalar for $kind {
            fn from_u64(value: u64) -> Self { value as Self }
            fn to_u64(self) -> u64 { self as u64 }
        })*
    };
}
scalars!(u32, u64, usize, i32, i64, f32, f64);

fn pipeline<T: Scalar, const N: usize>(input: &[T], seed: T) -> T {
    let scale = T::from_u64((N % 7 + 1) as u64);
    let offset = T::from_u64((N % 11 + 2) as u64);
    let mapped: Vec<_> = input.iter().copied()
        .enumerate()
        .map(|(index, value)| if index % 2 == 0 { value * scale } else { value + offset })
        .filter(|value| *value > seed)
        .collect();
    let grouped = mapped.chunks(N % 8 + 1)
        .map(|chunk| chunk.iter().copied().fold(seed, |left, right| left + right));
    let windows = mapped.windows(2)
        .map(|window| window[1] - window[0]);
    grouped.zip(windows.chain(std::iter::repeat(seed)))
        .map(|(left, right)| left * scale + right)
        .take(input.len() / 2 + N)
        .fold(offset, |left, right| left + right)
}

macro_rules! cases {
    ($(($name:ident, $index:expr)),* $(,)?) => {
        $(fn $name<T: Scalar>(input: &[T], seed: T) -> T {
            pipeline::<T, $index>(input, seed)
        })*

        fn dispatch<T: Scalar>(input: &[T], seed: T) -> u64 {
            0 $(^ $name(input, seed).to_u64())*
        }
    };
}

cases!(
    (case_00, 0), (case_01, 1), (case_02, 2), (case_03, 3),
    (case_04, 4), (case_05, 5), (case_06, 6), (case_07, 7),
    (case_08, 8), (case_09, 9), (case_10, 10), (case_11, 11),
    (case_12, 12), (case_13, 13), (case_14, 14), (case_15, 15),
    (case_16, 16), (case_17, 17), (case_18, 18), (case_19, 19),
    (case_20, 20), (case_21, 21), (case_22, 22), (case_23, 23),
    (case_24, 24), (case_25, 25), (case_26, 26), (case_27, 27),
    (case_28, 28), (case_29, 29), (case_30, 30), (case_31, 31),
);

fn typed_run<T: Scalar>(seed: u64) -> u64 {
    let input: Vec<T> = (0..1024)
        .map(|index| T::from_u64(seed.wrapping_add(index) & 1023))
        .collect();
    dispatch(&input, T::from_u64(seed & 31))
}

pub fn run(seed: u64) -> u64 {
    typed_run::<u32>(seed) ^ typed_run::<u64>(seed) ^ typed_run::<usize>(seed)
        ^ typed_run::<i32>(seed) ^ typed_run::<i64>(seed)
        ^ typed_run::<f32>(seed) ^ typed_run::<f64>(seed)
}
