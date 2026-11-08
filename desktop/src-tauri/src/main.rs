// Pas de console en plus de la fenêtre sous Windows.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    finz_local_connector_desktop_lib::run()
}
