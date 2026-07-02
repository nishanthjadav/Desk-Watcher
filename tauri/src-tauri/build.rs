fn main() {
    // Emits the resources, capability manifests, and icon metadata that
    // `tauri build` reads. The empty attributes match every Tauri v2 crate
    // I've seen — customization goes through tauri.conf.json, not here.
    tauri_build::build()
}
