; ============================================================
; ZERE — Inno Setup script (Windows Installer GUI)
;
; Компиляция:
;   installer\build-setup.ps1              (стандартный режим)
;   installer\build-setup.ps1 -Edition both
;   или вручную:
;   ISCC.exe /DStageDir=installer\stage /DEdition=python installer\Zere.iss
;
; StageDir — каталог с исходниками (наполняется git-архивом
; build-setup.ps1, чтобы в дистрибутив не попали .git, .venv,
; bin/obj, кэш и локальные данные).
; ============================================================

#ifndef StageDir
  #define StageDir ".\stage"
#endif
#ifndef Edition
  ; Редакция по умолчанию для ручного запуска ISCC. build-setup.ps1 всегда
  ; передаёт -DEdition явно (по умолчанию — both: дистрибутив несёт обе редакции).
  #define Edition "both"
#endif
#ifndef FileVersion
  #define FileVersion "1.8.0.0"
#endif
; Версию задаёт build-setup.ps1 (/DMyAppVersion из config/config.json) —
; иначе она расходилась бы с версией в конфиге и в свойствах файла.
#ifndef MyAppVersion
  #define MyAppVersion "1.8.0"
#endif

#define MyAppName "ZERE"
#define MyAppPublisher "ZERE Project"
#define MyAppURL "https://github.com/oneleft12/Zere"
; Ярлык Inno создаётся до install.ps1 (он перезапишет его на zere.exe или
; pythonw при Smart App Control). ZERE.bat — безопасный стартовый путь.
#define MyAppExeName "ZERE.bat"

[Setup]
AppId={{5E7A1C42-93B8-4F6D-A2E1-7C4D0B9F3A55}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
VersionInfoVersion={#FileVersion}
VersionInfoProductTextVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableProgramGroupPage=yes
; Установка без прав администратора (per-user)
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=ZereInstaller
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}
CloseApplications=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительно:"
Name: "startmenuicon"; Description: "Добавить в меню «Пуск»"; GroupDescription: "Дополнительно:"

[Files]
; Весь staged-дистрибутив (git archive без .git/.venv/bin/obj/данных)
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
; Страховочные ярлыки: install.ps1 создаёт такие же, они просто перезапишутся
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userprograms}\{#MyAppName}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: startmenuicon

[Run]
; Настройку (venv, зависимости, Ollama/модель, голос, ярлыки, smoke-тест)
; запускает секция [Code] ниже — там проверяется код возврата install.ps1.
; Через [Run] мастер показывал «Установка завершена» даже когда pip не поставил
; зависимости: пользователь узнавал об этом только при запуске ZERE, уже с
; ошибкой «No module named ...». Окно консоли НЕ скрыто — виден ход установки.

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Params: String;
  LogPath: String;
begin
  if CurStep <> ssPostInstall then
    Exit;

  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\installer\install.ps1') +
            '" -Prefix "' + ExpandConstant('{app}') + '" -Edition {#Edition} -Yes -NoLaunch';

  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params,
              ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, ResultCode) then
  begin
    if not WizardSilent then
      MsgBox('Не удалось запустить настройку ZERE (installer\install.ps1).' + #13#10 +
             'Файлы скопированы, но окружение (зависимости, модели, ярлыки) не настроено.',
             mbError, MB_OK);
    Exit;
  end;

  if ResultCode <> 0 then
  begin
    LogPath := ExpandConstant('{app}') + '\installer\install-log.txt';
    if not WizardSilent then
      MsgBox('Настройка ZERE завершилась с ошибкой (код ' + IntToStr(ResultCode) + ').' + #13#10 + #13#10 +
             'Файлы программы установлены, но зависимости или модели — не полностью,' + #13#10 +
             'поэтому ZERE может не запуститься.' + #13#10 + #13#10 +
             'Полный лог: ' + LogPath + #13#10 + #13#10 +
             'Устраните причину и запустите installer\install.ps1 ещё раз — установка идемпотентна.',
             mbError, MB_OK);
  end;
end;

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\uninstall.ps1"" -Prefix ""{app}"" -Yes"; \
    RunOnceId: "UninstallZere"; \
    Flags: waituntilterminated

[UninstallDelete]
; Всё, что создали мы (могло быть создано install.ps1 вне журнала Inno)
Type: files; Name: "{app}\ZERE.bat"
; install.ps1 мог собрать приложение уже после копирования файлов
Type: files; Name: "{app}\zere.exe"
Type: files; Name: "{app}\installer\install-manifest.json"
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\publish"
; Скачано install.ps1 (вне журнала Inno) + кэш компиляции smoke-теста
Type: filesandordirs; Name: "{app}\ZERE.Voice"
Type: filesandordirs; Name: "{app}\zere"
Type: filesandordirs; Name: "{app}\__pycache__"
; Ярлыки могли быть созданы install.ps1 (вне журнала Inno)
Type: files; Name: "{userdesktop}\{#MyAppName}.lnk"
Type: files; Name: "{userdesktop}\ZERE - panel.url"
Type: filesandordirs; Name: "{userprograms}\{#MyAppName}"
