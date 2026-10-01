//! Sixty-four binary record types, each with one eight-field procedural derive.

use record_derive::WireRecord;

pub trait WireField {
    fn encode(&self, output: &mut Vec<u8>);
    fn checksum(&self) -> u64;
}

pub trait WireRecord {
    const FIELD_NAMES: &'static [&'static str];
    fn encode(&self, output: &mut Vec<u8>);
    fn checksum(&self) -> u64;
}

fn byte_checksum(bytes: &[u8]) -> u64 {
    bytes.iter().fold(0xcbf29ce484222325, |state, byte| {
        (state ^ u64::from(*byte)).wrapping_mul(0x100000001b3)
    })
}

macro_rules! integer_fields {
    ($($kind:ty),* $(,)?) => {
        $(impl WireField for $kind {
            fn encode(&self, output: &mut Vec<u8>) {
                output.extend_from_slice(&self.to_le_bytes());
            }
            fn checksum(&self) -> u64 {
                byte_checksum(&self.to_le_bytes())
            }
        })*
    };
}
integer_fields!(u8, u16, u32, u64);

impl WireField for bool {
    fn encode(&self, output: &mut Vec<u8>) {
        output.push(u8::from(*self));
    }
    fn checksum(&self) -> u64 {
        byte_checksum(&[u8::from(*self)])
    }
}

impl<const N: usize> WireField for [u8; N] {
    fn encode(&self, output: &mut Vec<u8>) {
        output.extend_from_slice(self);
    }
    fn checksum(&self) -> u64 {
        byte_checksum(self)
    }
}

macro_rules! records {
    ($($record:ident),* $(,)?) => {
        $(#[derive(WireRecord)]
        pub struct $record {
            pub sequence: u64,
            pub timestamp: u64,
            pub checksum: u32,
            pub version: u16,
            pub category: u8,
            pub active: bool,
            pub fingerprint: [u8; 16],
            pub payload: [u8; 32],
        }

        const _: [(); 8] = [(); <$record as WireRecord>::FIELD_NAMES.len()];)*

        pub fn encode_records(seed: u64) -> (Vec<u8>, u64) {
            let mut output = Vec::with_capacity(64 * 72);
            let mut checksum = 0_u64;
            let mut index = 0_u64;
            $(let record = $record {
                sequence: seed.wrapping_add(index),
                timestamp: seed.rotate_left(index as u32),
                checksum: (seed ^ index) as u32,
                version: index as u16,
                category: (index % 7) as u8,
                active: index % 2 == 0,
                fingerprint: [index as u8; 16],
                payload: [seed.wrapping_add(index) as u8; 32],
            };
            WireRecord::encode(&record, &mut output);
            checksum = checksum.rotate_left(1) ^ WireRecord::checksum(&record);
            index += 1;)*
            assert_eq!(index, 64);
            assert_eq!(output.len(), 64 * 72);
            (output, checksum)
        }
    };
}

records!(
    Record00, Record01, Record02, Record03, Record04, Record05, Record06, Record07,
    Record08, Record09, Record10, Record11, Record12, Record13, Record14, Record15,
    Record16, Record17, Record18, Record19, Record20, Record21, Record22, Record23,
    Record24, Record25, Record26, Record27, Record28, Record29, Record30, Record31,
    Record32, Record33, Record34, Record35, Record36, Record37, Record38, Record39,
    Record40, Record41, Record42, Record43, Record44, Record45, Record46, Record47,
    Record48, Record49, Record50, Record51, Record52, Record53, Record54, Record55,
    Record56, Record57, Record58, Record59, Record60, Record61, Record62, Record63,
);
