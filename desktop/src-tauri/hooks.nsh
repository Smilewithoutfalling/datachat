; 阶段 6 D1：卸载页的「删除应用数据」勾选框默认不勾（phase6-desktop.md §1 第 4 条）。
; Tauri 自带的勾选框只删 %LOCALAPPDATA%\<identifier>，而数据目录是 %LOCALAPPDATA%\datachat
; （和浏览器模式 python -m app.server --open 共用同一份数据），所以在这里补删。
; 钥匙串里的 Key 不删：卸载器拿不到 keyring，手动删见 README「卸载」。
!macro NSIS_HOOK_POSTUNINSTALL
  ${If} $DeleteAppDataCheckboxState = 1
    RMDir /r "$LOCALAPPDATA\datachat"
  ${EndIf}
!macroend
