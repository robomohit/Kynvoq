; Orynn online installer (Inno Setup 6.1+).
; A tiny OrynnSetup.exe that DOWNLOADS the Orynn payload from a GitHub release,
; extracts it, and makes shortcuts. First launch of Orynn.exe shows the key window
; (the onboarding), so the installer + app together onboard the user.
;
; Build: install Inno Setup, then run `iscc packaging\orynn_online_setup.iss`.
; Update PayloadUrl to your published release asset before shipping.

#define AppName "Orynn"
#define AppVersion "1.0.0"
#define PayloadUrl "https://github.com/robomohit/Orynn/releases/latest/download/Orynn-win64.zip"
#define ExeName "Orynn.exe"

[Setup]
AppId={{B7C2F1A0-ORYN-4A11-9C3E-ORYNNSETUP01}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=OrynnSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; small bootstrapper — the real payload is pulled at install time
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#ExeName}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#ExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Run]
Filename: "{app}\{#ExeName}"; Description: "Launch Orynn"; Flags: nowait postinstall skipifsilent

[Code]
var
  DownloadPage: TDownloadWizardPage;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing),
    'Downloading Orynn — this is the one-time payload.', nil);
end;

procedure ExtractZip(ZipPath, TargetDir: string);
var
  Shell, Source, Target: Variant;
begin
  ForceDirectories(TargetDir);
  Shell := CreateOleObject('Shell.Application');
  Source := Shell.NameSpace(ZipPath);
  Target := Shell.NameSpace(TargetDir);
  // 20 = no progress dialog (4) + yes-to-all (16)
  Target.CopyHere(Source.Items, 20);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  ZipPath: string;
begin
  Result := True;
  if CurPageID = wpReady then begin
    DownloadPage.Clear;
    DownloadPage.Add('{#PayloadUrl}', 'Orynn-win64.zip', '');
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
        ZipPath := ExpandConstant('{tmp}\Orynn-win64.zip');
        ExtractZip(ZipPath, ExpandConstant('{app}'));
      except
        if DownloadPage.AbortedByUser then
          Log('Download aborted by user.')
        else
          SuppressibleMsgBox(AddPeriod(GetExceptionMessage), mbCriticalError, MB_OK, IDOK);
        Result := False;
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;
