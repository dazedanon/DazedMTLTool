//! DXLib codecs: the Huffman decoder and the LZSS ("DXA") decompressor.

use crate::*;
use std::io;

#[derive(Clone, Copy)]
pub(crate) struct HuffNode {
    weight: u32,
    child: [i32; 2],
    parent: i32,
    index: u8,
    bit_num: u8,
    bit_array: [u8; 32],
}

/// MSB-first bit reader over the Huffman header bitstream.
pub(crate) struct BitReader<'a> {
    data: &'a [u8],
    byte: usize,
    bit: u8,
}

impl<'a> BitReader<'a> {
    fn new(data: &'a [u8]) -> Self {
        Self {
            data,
            byte: 0,
            bit: 0,
        }
    }

    fn read(&mut self, bits: u8) -> io::Result<u64> {
        let mut out = 0u64;
        for i in 0..bits {
            let b = *self
                .data
                .get(self.byte)
                .ok_or_else(|| invalid("huffman bitstream ended early"))?;
            out |= (((b >> (7 - self.bit)) & 1) as u64) << (bits - 1 - i);
            self.bit += 1;
            if self.bit == 8 {
                self.byte += 1;
                self.bit = 0;
            }
        }
        Ok(out)
    }

    fn bytes(&self) -> usize {
        self.byte + usize::from(self.bit != 0)
    }
}

pub(crate) fn huffman_decode(src: &[u8]) -> io::Result<Vec<u8>> {
    let mut br = BitReader::new(src);
    let original_bits = br.read(6)? as u8 + 1;
    let original_size = br.read(original_bits)? as usize;
    if original_size > MAX_DECODE_SIZE {
        return Err(invalid(format!(
            "huffman output is implausibly large: {original_size}"
        )));
    }
    let press_bits = br.read(6)? as u8 + 1;
    let _press_size = br.read(press_bits)?;

    let mut weight = [0u16; 256];
    let mut bit_num = (br.read(3)? as u8 + 1) * 2;
    let _ = br.read(1)?;
    let mut save = br.read(bit_num)? as u16;
    weight[0] = save;
    for i in 1..256 {
        bit_num = (br.read(3)? as u8 + 1) * 2;
        let minus = br.read(1)?;
        save = br.read(bit_num)? as u16;
        weight[i] = if minus == 1 {
            weight[i - 1].wrapping_sub(save)
        } else {
            weight[i - 1].wrapping_add(save)
        };
    }

    let head_size = br.bytes();
    if head_size >= src.len() {
        return Err(invalid("huffman body missing"));
    }

    let mut nodes = vec![
        HuffNode {
            weight: 0,
            child: [-1, -1],
            parent: -1,
            index: 0,
            bit_num: 0,
            bit_array: [0; 32],
        };
        511
    ];
    for i in 0..511 {
        nodes[i].weight = if i < 256 { weight[i] as u32 } else { 0 };
    }

    let mut data_num = 256usize;
    let mut node_num = 256usize;
    while data_num > 1 {
        let mut min1: i32 = -1;
        let mut min2: i32 = -1;
        let mut valid = 0usize;
        let mut node_index = 0usize;
        while valid < data_num {
            if nodes[node_index].parent != -1 {
                node_index += 1;
                continue;
            }
            valid += 1;
            if min1 == -1 || nodes[min1 as usize].weight > nodes[node_index].weight {
                min2 = min1;
                min1 = node_index as i32;
            } else if min2 == -1 || nodes[min2 as usize].weight > nodes[node_index].weight {
                min2 = node_index as i32;
            }
            node_index += 1;
        }

        let a = min1 as usize;
        let b = min2 as usize;
        nodes[node_num].weight = nodes[a].weight + nodes[b].weight;
        nodes[node_num].child = [min1, min2];
        nodes[a].index = 0;
        nodes[b].index = 1;
        nodes[a].parent = node_num as i32;
        nodes[b].parent = node_num as i32;
        node_num += 1;
        data_num -= 1;
    }

    for i in 0..510 {
        let mut temp = [0u8; 32];
        let mut temp_index = 0usize;
        let mut temp_count = 0u8;
        let mut n = i;
        while nodes[n].parent != -1 {
            if temp_count == 8 {
                temp_count = 0;
                temp_index += 1;
            }
            temp[temp_index] <<= 1;
            temp[temp_index] |= nodes[n].index;
            temp_count += 1;
            nodes[i].bit_num += 1;
            n = nodes[n].parent as usize;
        }

        let mut bit_count = 0u8;
        let mut bit_index = 0usize;
        while temp_index < temp.len() {
            if bit_count == 8 {
                bit_count = 0;
                bit_index += 1;
            }
            nodes[i].bit_array[bit_index] |= (temp[temp_index] & 1) << bit_count;
            temp[temp_index] >>= 1;
            temp_count = temp_count.wrapping_sub(1);
            if temp_count == 0 {
                if temp_index == 0 {
                    break;
                }
                temp_index -= 1;
                temp_count = 8;
            }
            bit_count += 1;
        }
    }

    let mut bitmask = [0u16; 9];
    for i in 0..9 {
        bitmask[i] = (1u16 << (i + 1)) - 1;
    }
    let mut node_index_table = [-1i32; 512];
    for i in 0..512usize {
        for j in 0..510usize {
            let bn = nodes[j].bit_num;
            if bn == 0 || bn > 9 {
                continue;
            }
            let bit_array_01 = nodes[j].bit_array[0] as u16 | ((nodes[j].bit_array[1] as u16) << 8);
            if (i as u16 & bitmask[bn as usize - 1]) == (bit_array_01 & bitmask[bn as usize - 1]) {
                node_index_table[i] = j as i32;
                break;
            }
        }
    }

    let press = &src[head_size..];
    let mut out = vec![0u8; original_size];
    let mut press_counter = 0usize;
    let mut press_bit_counter = 0u8;
    let mut press_bit_data = *press.first().ok_or_else(|| invalid("empty huffman body"))? as u16;

    for dest_counter in 0..original_size {
        let mut node_index: i32;
        if dest_counter >= original_size.saturating_sub(17) {
            node_index = 510;
        } else {
            if press_bit_counter == 8 {
                press_counter += 1;
                press_bit_data = *press
                    .get(press_counter)
                    .ok_or_else(|| invalid("huffman body ended early"))?
                    as u16;
                press_bit_counter = 0;
            }
            let next = *press.get(press_counter + 1).unwrap_or(&0) as u16;
            press_bit_data = (press_bit_data | (next << (8 - press_bit_counter))) & 0x1ff;
            node_index = node_index_table[press_bit_data as usize];
            if node_index < 0 {
                return Err(invalid("bad huffman lookup"));
            }
            press_bit_counter += nodes[node_index as usize].bit_num;
            if press_bit_counter >= 16 {
                press_counter += 2;
                press_bit_counter -= 16;
                press_bit_data =
                    (*press.get(press_counter).unwrap_or(&0) as u16) >> press_bit_counter;
            } else if press_bit_counter >= 8 {
                press_counter += 1;
                press_bit_counter -= 8;
                press_bit_data =
                    (*press.get(press_counter).unwrap_or(&0) as u16) >> press_bit_counter;
            } else {
                press_bit_data >>= nodes[node_index as usize].bit_num;
            }
        }

        while node_index > 255 {
            if press_bit_counter == 8 {
                press_counter += 1;
                press_bit_data = *press
                    .get(press_counter)
                    .ok_or_else(|| invalid("huffman body ended early"))?
                    as u16;
                press_bit_counter = 0;
            }
            let index = (press_bit_data & 1) as usize;
            press_bit_data >>= 1;
            press_bit_counter += 1;
            node_index = nodes[node_index as usize].child[index];
        }
        out[dest_counter] = node_index as u8;
    }

    Ok(out)
}

pub(crate) fn dxa_decode(src: &[u8]) -> io::Result<Vec<u8>> {
    if src.len() < 9 {
        return Err(invalid("lz source too small"));
    }
    let dest_size = read_u32(src) as usize;
    if dest_size > MAX_DECODE_SIZE {
        return Err(invalid(format!(
            "lz output is implausibly large: {dest_size}"
        )));
    }
    let packed_total = read_u32(&src[4..]) as usize;
    if packed_total < 9 || packed_total > src.len() {
        return Err(invalid("lz packed size is invalid"));
    }
    let mut src_left = packed_total - 9;
    let key_code = src[8];
    let mut sp = 9usize;
    let mut out = Vec::with_capacity(dest_size);

    while src_left > 0 {
        let b = *src
            .get(sp)
            .ok_or_else(|| invalid("lz source ended early"))?;
        if b != key_code {
            out.push(b);
            sp += 1;
            src_left -= 1;
            continue;
        }

        let b1 = *src
            .get(sp + 1)
            .ok_or_else(|| invalid("lz source ended early"))?;
        if b1 == key_code {
            out.push(key_code);
            sp += 2;
            src_left = src_left.saturating_sub(2);
            continue;
        }

        let mut code = b1;
        if code > key_code {
            code -= 1;
        }
        sp += 2;
        src_left = src_left.saturating_sub(2);

        let mut conbo = (code >> 3) as usize;
        if (code & 4) != 0 {
            conbo |= (*src
                .get(sp)
                .ok_or_else(|| invalid("lz source ended early"))? as usize)
                << 5;
            sp += 1;
            src_left = src_left.saturating_sub(1);
        }
        conbo += 4;

        let index_size = code & 3;
        let mut index = match index_size {
            0 => {
                let v = *src
                    .get(sp)
                    .ok_or_else(|| invalid("lz source ended early"))?
                    as usize;
                sp += 1;
                src_left = src_left.saturating_sub(1);
                v
            }
            1 => {
                if sp + 2 > src.len() {
                    return Err(invalid("lz source ended early"));
                }
                let v = read_u16(&src[sp..]) as usize;
                sp += 2;
                src_left = src_left.saturating_sub(2);
                v
            }
            2 => {
                if sp + 3 > src.len() {
                    return Err(invalid("lz source ended early"));
                }
                let v = read_u16(&src[sp..]) as usize | ((src[sp + 2] as usize) << 16);
                sp += 3;
                src_left = src_left.saturating_sub(3);
                v
            }
            _ => return Err(invalid("unsupported lz index size")),
        };
        index += 1;
        if index > out.len() {
            return Err(invalid("lz back-reference before output start"));
        }
        for _ in 0..conbo {
            let v = out[out.len() - index];
            out.push(v);
        }
    }

    if out.len() != dest_size {
        return Err(invalid(format!(
            "lz decoded {} bytes, expected {}",
            out.len(),
            dest_size
        )));
    }
    Ok(out)
}
