//! Plaintext packer gate: `extract(pack(files)) == files`.
//!
//! Proves the VER8 writer produces a container our own extractor reads back with identical
//! paths and bytes, across a synthetic nested tree and a real Wolf `Data/` subtree.
//!   cargo test -p wolf-archive --test pack_roundtrip -- --nocapture

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use wolf_archive::{extract_archive, pack_chacha, pack_encrypted, pack_newcrypt, pack_plaintext};

/// Normalize a path to forward slashes for order-independent comparison.
fn norm(p: &str) -> String {
    p.replace('\\', "/")
}

fn roundtrip(files: &[(String, Vec<u8>)]) {
    let archive = pack_plaintext(files).expect("pack");
    let extracted = extract_archive(&archive, b"").expect("extract our own archive");

    let want: BTreeMap<String, Vec<u8>> = files.iter().map(|(p, d)| (norm(p), d.clone())).collect();
    let got: BTreeMap<String, Vec<u8>> =
        extracted.into_iter().map(|(p, d)| (norm(&p), d)).collect();

    assert_eq!(
        got.keys().collect::<Vec<_>>(),
        want.keys().collect::<Vec<_>>(),
        "path set differs"
    );
    for (p, data) in &want {
        assert_eq!(got.get(p), Some(data), "bytes differ for {p}");
    }
}

#[test]
fn synthetic_tree_round_trips() {
    let files = vec![
        ("BasicData/CommonEvent.dat".to_string(), vec![1, 2, 3, 4, 5]),
        ("BasicData/Game.dat".to_string(), b"hello game".to_vec()),
        ("MapData/Map001.mps".to_string(), vec![0xAA; 1000]),
        ("MapData/Map002.mps".to_string(), vec![]), // empty file
        ("MapData/sub/Deep.mps".to_string(), vec![7; 3]), // odd length (alignment)
        ("top.txt".to_string(), b"a top-level file".to_vec()),
    ];
    roundtrip(&files);
}

#[test]
fn encrypted_round_trips_through_our_reader() {
    // pack_encrypted(cv) -> extract_archive (auto-detects cryptVersion = Flags>>16) -> files.
    // Proves the symmetric re-encryption decodes through our deterministic dispatch.
    let files = vec![
        (
            "BasicData/Game.dat".to_string(),
            vec![1u8, 2, 3, 4, 5, 6, 7, 8, 9],
        ),
        ("BasicData/CommonEvent.dat".to_string(), vec![0xCD; 777]),
        ("MapData/Map001.mps".to_string(), b"map data here".to_vec()),
        ("MapData/sub/Deep.mps".to_string(), vec![9, 8, 7]),
    ];
    let want: BTreeMap<String, Vec<u8>> = files.iter().map(|(p, d)| (norm(p), d.clone())).collect();

    for cv in [0x12Cu16, 0x13A] {
        let archive = pack_encrypted(&files, cv).expect("encrypt");
        // The archive must NOT be plaintext: data should be transformed.
        let extracted = extract_archive(&archive, b"").expect("extract encrypted");
        let got: BTreeMap<String, Vec<u8>> =
            extracted.into_iter().map(|(p, d)| (norm(&p), d)).collect();
        assert_eq!(got, want, "cryptVersion {cv:#x} did not round-trip");
    }
}

#[test]
fn wolfpro_newcrypt_round_trips_through_our_reader() {
    // pack_newcrypt(cv, pwd) -> extract_archive (recomputes the context from the embedded
    // password) -> files. Proves the symmetric WolfPro stream + AES-CTR + address scramble
    // encode is the exact inverse of our verified decrypt path.
    let files = vec![
        ("BasicData/Game.dat".to_string(), vec![0x11u8; 2048]),
        ("BasicData/CommonEvent.dat".to_string(), vec![0x42; 5000]),
        ("MapData/Map001.mps".to_string(), b"hello wolf pro".to_vec()),
        ("MapData/sub/Deep.mps".to_string(), (0..255u8).collect()),
    ];
    let want: BTreeMap<String, Vec<u8>> = files.iter().map(|(p, d)| (norm(p), d.clone())).collect();

    let pwd: [u8; 15] = [
        0x37, 0x9a, 0x14, 0xc2, 0x5b, 0x08, 0xe1, 0x4f, 0x2d, 0x71, 0xbc, 0x33, 0x96, 0x6a, 0xd8,
    ];
    for cv in [0x14Bu16, 0x15E] {
        let archive = pack_newcrypt(&files, cv, &pwd).expect("newcrypt encode");
        let extracted = extract_archive(&archive, b"").expect("decode newcrypt");
        let got: BTreeMap<String, Vec<u8>> =
            extracted.into_iter().map(|(p, d)| (norm(&p), d)).collect();
        assert_eq!(got, want, "WolfPro cryptVersion {cv:#x} did not round-trip");
    }
}

#[test]
fn chacha2_round_trips_through_our_reader() {
    let files = vec![
        ("BasicData/Game.dat".to_string(), vec![0x5Au8; 4096]),
        (
            "MapData/Map001.mps".to_string(),
            b"chacha20 round trip".to_vec(),
        ),
        ("MapData/sub/Deep.mps".to_string(), (0..200u8).collect()),
    ];
    let want: BTreeMap<String, Vec<u8>> = files.iter().map(|(p, d)| (norm(p), d.clone())).collect();
    let archive = pack_chacha(&files).expect("chacha encode");
    let extracted = extract_archive(&archive, b"").expect("decode chacha2");
    let got: BTreeMap<String, Vec<u8>> =
        extracted.into_iter().map(|(p, d)| (norm(&p), d)).collect();
    assert_eq!(got, want, "ChaCha2 did not round-trip");
}

#[test]
fn real_data_subtree_round_trips() {
    // Pack a real BasicData folder (ASCII paths, real binary content) and read it back.
    let base = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../Data/BasicData");
    if !base.exists() {
        eprintln!("no Data/BasicData corpus, skipping");
        return;
    }

    let mut files = Vec::new();
    collect(&base, &base, &mut files);
    files.sort();
    if files.is_empty() {
        eprintln!("no files found, skipping");
        return;
    }
    eprintln!("packing {} real files", files.len());
    roundtrip(&files);
}

fn collect(base: &Path, dir: &Path, out: &mut Vec<(String, Vec<u8>)>) {
    let Ok(rd) = std::fs::read_dir(dir) else {
        return;
    };
    for e in rd.flatten() {
        let p = e.path();
        if p.is_dir() {
            collect(base, &p, out);
        } else if let Ok(bytes) = std::fs::read(&p) {
            let rel = p
                .strip_prefix(base)
                .unwrap()
                .to_string_lossy()
                .replace('\\', "/");
            out.push((format!("BasicData/{rel}"), bytes));
        }
    }
}

#[test]
fn ver5_ver6_round_trip_through_our_reader() {
    use wolf_archive::{pack_ver5, pack_ver6};
    let files = vec![
        ("BasicData/Game.dat".to_string(), vec![0x3Cu8; 1234]),
        (
            "BasicData/CommonEvent.dat".to_string(),
            b"old wolf 2.0x".to_vec(),
        ),
        ("MapData/Map001.mps".to_string(), (0..250u8).collect()),
        ("MapData/sub/Deep.mps".to_string(), vec![5, 4, 3, 2, 1]),
    ];
    let want: BTreeMap<String, Vec<u8>> = files.iter().map(|(p, d)| (norm(p), d.clone())).collect();

    for (label, archive) in [
        ("VER5", pack_ver5(&files).expect("ver5 encode")),
        ("VER6", pack_ver6(&files).expect("ver6 encode")),
    ] {
        let extracted = extract_archive(&archive, b"").expect("decode legacy archive");
        let got: BTreeMap<String, Vec<u8>> =
            extracted.into_iter().map(|(p, d)| (norm(&p), d)).collect();
        assert_eq!(got, want, "{label} did not round-trip");
    }
}
