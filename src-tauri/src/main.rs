// Prevents additional console window on Windows in both debug and release builds.
#![cfg_attr(windows, windows_subsystem = "windows")]

fn main() {
    app_lib::run();
}
