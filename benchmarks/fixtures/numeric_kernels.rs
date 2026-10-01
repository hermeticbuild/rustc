//! Const-generic numerical kernels with vectorizable and dependency-heavy loops.

#[inline(never)]
fn matrix<const N: usize>(input: &[f64], seed: f64) -> f64 {
    let mut left = [[0_f64; N]; N];
    let mut right = [[0_f64; N]; N];
    let mut product = [[0_f64; N]; N];
    for row in 0..N {
        for column in 0..N {
            left[row][column] = input[(row * N + column) % input.len()] + seed;
            right[row][column] = input[(column * N + row) % input.len()] - seed;
        }
    }
    for row in 0..N {
        for inner in 0..N {
            for column in 0..N {
                product[row][column] += left[row][inner] * right[inner][column];
            }
        }
    }
    product.iter().enumerate().map(|(index, row)| row[index]).sum()
}

#[inline(never)]
fn filter<const WIDTH: usize>(input: &[f64], output: &mut [f64]) {
    let mut weights = [0_f64; WIDTH];
    for (index, weight) in weights.iter_mut().enumerate() {
        *weight = 1.0 / (index as f64 + 1.0);
    }
    for (index, destination) in output.iter_mut().enumerate() {
        let mut value = 0.0;
        for offset in 0..WIDTH {
            value += input[(index + offset) % input.len()] * weights[offset];
        }
        *destination = value;
    }
}

#[inline(never)]
fn mix<const ROUNDS: usize>(input: &[u64], seed: u64) -> u64 {
    let mut state = [seed, seed.rotate_left(13), !seed, seed.wrapping_mul(17)];
    for &value in input {
        state[0] ^= value;
        for round in 0..ROUNDS {
            state[0] = state[0].wrapping_add(state[1]).rotate_left(13);
            state[1] = (state[1] ^ state[2]).rotate_left(17);
            state[2] = state[2].wrapping_mul(0x9e3779b97f4a7c15).wrapping_add(round as u64);
            state[3] = (state[3] ^ state[0]).rotate_left(23);
            state.swap(round % 4, (round + 1) % 4);
        }
    }
    state.iter().copied().fold(0, |left, right| left ^ right)
}

macro_rules! all_matrices {
    ($input:expr, $seed:expr, $($size:expr),* $(,)?) => {
        0.0 $(+ matrix::<$size>($input, $seed))*
    };
}

macro_rules! all_filters {
    ($input:expr, $output:expr, $($size:expr),* $(,)?) => {
        $(filter::<$size>($input, $output);)*
    };
}

macro_rules! all_mixers {
    ($input:expr, $seed:expr, $($size:expr),* $(,)?) => {
        0 $(^ mix::<$size>($input, $seed))*
    };
}

pub fn run(input: &[f64], integers: &[u64], seed: u64) -> (f64, u64) {
    if input.is_empty() { return (0.0, 0); }
    let mut output = vec![0.0; input.len()];
    all_filters!(input, &mut output, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17);
    let matrices = all_matrices!(input, seed as f64, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16);
    let mixed = all_mixers!(integers, seed, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 20, 24, 32);
    (matrices + output.iter().sum::<f64>(), mixed)
}
