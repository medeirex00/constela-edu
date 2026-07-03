// Impede a janela de console extra no Windows em builds de produção.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    sgpe_desktop_lib::run()
}
