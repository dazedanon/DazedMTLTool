//! `wolf-unpack` CLI: thin wrapper over `wolf_archive::run`.

fn main() -> std::io::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    wolf_archive::run(&args)
}
