//! Constela Edu Desktop — shell nativo (Tauri 2) do app web.
//!
//! A atualização automática roda em Rust, na inicialização: verifica o
//! endpoint de releases, baixa/instala em segundo plano e reinicia o app.
//! Falha de rede é silenciosa — o app continua com a versão atual.

use tauri_plugin_updater::UpdaterExt;

async fn atualizar(app: tauri::AppHandle) -> tauri_plugin_updater::Result<()> {
    if let Some(atualizacao) = app.updater()?.check().await? {
        atualizacao
            .download_and_install(|_baixado, _total| {}, || {})
            .await?;
        app.restart();
    }
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .setup(|app| {
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                // Melhor esforço: erro de atualização nunca impede o uso
                let _ = atualizar(handle).await;
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("erro ao iniciar o Constela Edu Desktop");
}
