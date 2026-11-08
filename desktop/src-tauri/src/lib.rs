//! Coquille de l'application de bureau : icône près de l'horloge, fenêtre cachée plutôt que
//! fermée, une seule instance, démarrage avec l'ordinateur, mises à jour. La logique est dans
//! le connecteur Python, lancé par la fenêtre (`serve --stdio`, plugin shell).

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    AppHandle, Emitter, Manager, WindowEvent,
};
use tauri_plugin_autostart::MacosLauncher;

fn show(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| show(app)))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec!["--hidden"]),
        ))
        .setup(|app| {
            let open = MenuItem::with_id(app, "open", "Ouvrir", true, None::<&str>)?;
            let sync = MenuItem::with_id(app, "sync", "Synchroniser maintenant", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quitter", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &sync, &quit])?;

            let mut tray = TrayIconBuilder::with_id("main")
                .tooltip("Finz Connecteur local")
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => show(app),
                    "sync" => {
                        let _ = app.emit("tray-sync", ());
                    }
                    "quit" => app.exit(0),
                    _ => {}
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;

            // Lancé au démarrage de l'ordinateur : icône seulement, fenêtre cachée.
            if std::env::args().any(|arg| arg == "--hidden") {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.hide();
                }
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            // Fermer la fenêtre la cache : le connecteur continue de synchroniser.
            if let WindowEvent::CloseRequested { api, .. } = event {
                let _ = window.hide();
                api.prevent_close();
            }
        })
        .run(tauri::generate_context!())
        .expect("échec du démarrage de Finz Connecteur local");
}
