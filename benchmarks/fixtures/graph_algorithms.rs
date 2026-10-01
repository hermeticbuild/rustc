//! Collection-heavy graph algorithms instantiated for several integer types.

use std::cmp::Reverse;
use std::collections::{BTreeMap, BTreeSet, BinaryHeap, HashMap, VecDeque};
use std::hash::Hash;

trait Vertex: Copy + Eq + Ord + Hash {
    fn from_usize(value: usize) -> Self;
    fn to_usize(self) -> usize;
}

macro_rules! vertices {
    ($($kind:ty),* $(,)?) => {
        $(impl Vertex for $kind {
            fn from_usize(value: usize) -> Self { value as Self }
            fn to_usize(self) -> usize { self as usize }
        })*
    };
}
vertices!(u16, u32, u64, usize, i32, i64);

struct Graph<V: Vertex> {
    edges: BTreeMap<V, Vec<(V, u64)>>,
}

impl<V: Vertex> Graph<V> {
    fn generate<const DEGREE: usize>(count: usize, seed: u64) -> Self {
        let mut edges = BTreeMap::new();
        let mut state = seed;
        for index in 0..count {
            let entry = edges.entry(V::from_usize(index)).or_insert_with(Vec::new);
            for step in 0..DEGREE {
                state = state.wrapping_mul(6364136223846793005).wrapping_add(1);
                let next = (state as usize ^ index ^ step) % count;
                entry.push((V::from_usize(next), state % 127 + 1));
            }
            entry.sort_unstable();
            entry.dedup_by_key(|edge| edge.0);
        }
        Self { edges }
    }

    fn shortest_distances(&self, origin: V) -> HashMap<V, u64> {
        let mut distances = HashMap::new();
        let mut pending = BinaryHeap::new();
        distances.insert(origin, 0);
        pending.push(Reverse((0_u64, origin)));
        while let Some(Reverse((distance, vertex))) = pending.pop() {
            if distances.get(&vertex).copied() != Some(distance) {
                continue;
            }
            if let Some(edges) = self.edges.get(&vertex) {
                for &(next, weight) in edges {
                    let candidate = distance.saturating_add(weight);
                    let old = distances.entry(next).or_insert(u64::MAX);
                    if candidate < *old {
                        *old = candidate;
                        pending.push(Reverse((candidate, next)));
                    }
                }
            }
        }
        distances
    }

    fn breadth_first(&self, origin: V) -> Vec<V> {
        let mut visited = BTreeSet::new();
        let mut pending = VecDeque::from([origin]);
        let mut result = Vec::new();
        while let Some(vertex) = pending.pop_front() {
            if !visited.insert(vertex) {
                continue;
            }
            result.push(vertex);
            if let Some(edges) = self.edges.get(&vertex) {
                pending.extend(edges.iter().map(|edge| edge.0));
            }
        }
        result
    }

    fn reverse(&self) -> Self {
        let mut edges = BTreeMap::new();
        for (&origin, outgoing) in &self.edges {
            for &(destination, weight) in outgoing {
                edges.entry(destination).or_insert_with(Vec::new).push((origin, weight));
            }
        }
        Self { edges }
    }
}

fn summarize<V: Vertex, const DEGREE: usize>(count: usize, seed: u64) -> u64 {
    let graph = Graph::<V>::generate::<DEGREE>(count, seed);
    let reverse = graph.reverse();
    let distances = graph.shortest_distances(V::from_usize(0));
    let reachable = reverse.breadth_first(V::from_usize(count / 2));
    reachable.into_iter().map(|vertex| {
        distances.get(&vertex).copied().unwrap_or(0) ^ vertex.to_usize() as u64
    }).fold(0_u64, u64::wrapping_add)
}

fn typed_run<V: Vertex>(count: usize, seed: u64) -> u64 {
    summarize::<V, 2>(count, seed) ^ summarize::<V, 3>(count, seed)
        ^ summarize::<V, 5>(count, seed) ^ summarize::<V, 8>(count, seed)
}

pub fn run(count: usize, seed: u64) -> u64 {
    let count = count.clamp(1, 4096);
    typed_run::<u16>(count, seed) ^ typed_run::<u32>(count, seed)
        ^ typed_run::<u64>(count, seed) ^ typed_run::<usize>(count, seed)
        ^ typed_run::<i32>(count, seed) ^ typed_run::<i64>(count, seed)
}
