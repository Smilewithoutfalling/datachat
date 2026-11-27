; 阶段 6：卸载页的「删除应用数据」勾选框默认不勾（phase6-desktop.md §1 第 4 条）。
; Tauri 自带的勾选框只删 %LOCALAPPDATA%\<identifier>；DataChat 的数据文件夹由 installer.nsi
; 在 un.onInit 里读出（DATACHAT_HOME → 注册表 DataDir → %LOCALAPPDATA%\datachat），放在 $UnDataDir。
;
; 数据文件夹可能是用户自选的（例如 D:\ 或「我的文档」），所以这里**只删 DataChat 自己的文件**，
; 最后对文件夹做一次不递归的 RMDir：里面还有别的东西就留着（phase6-desktop.md §3b 第 5 条）。
; 只有文件夹里有 datachat.db（确认是 DataChat 的数据文件夹）才动手；安装器也只接受空文件夹或已有
; datachat.db 的文件夹（installer.nsi ValidateDataDir），所以 datasets\、charts\ 只可能是 DataChat 建的。
; 数据文件夹来自环境变量 DATACHAT_HOME 时（$UnFromEnv=1）一律不删：那个文件夹安装器从没校验过（审查第二轮问题 2）。
; 清单与 app/server 实际落盘的位置对应：datachat.db（SQLite，含 -wal/-shm/-journal）、
; datasets\、charts\（app.py create_app）、server.log（__main__.py）。tests/test_desktop_installer.py 钉住这份清单。
; 钥匙串里的 Key 不删：卸载器拿不到 keyring，手动删见 README「卸载」。
!macro NSIS_HOOK_POSTUNINSTALL
  ${If} $DeleteAppDataCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
  ${AndIf} $UnDataDir != ""
  ${AndIf} $UnFromEnv <> 1
  ${AndIf} ${FileExists} "$UnDataDir\datachat.db"
    Delete "$UnDataDir\datachat.db"
    Delete "$UnDataDir\datachat.db-wal"
    Delete "$UnDataDir\datachat.db-shm"
    Delete "$UnDataDir\datachat.db-journal"
    Delete "$UnDataDir\server.log"
    RMDir /r "$UnDataDir\datasets"
    RMDir /r "$UnDataDir\charts"
    RMDir "$UnDataDir"
  ${EndIf}
!macroend
