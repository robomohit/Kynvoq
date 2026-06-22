# Windows URIs, Protocols, and Shell Namespace

**Date:** 2026-06-22  
**Audience:** Orynn desktop automation agents  
**Machine tested:** Windows 11 (build 26200)  
**Official references:**
- [Launch Windows Settings (ms-settings:)](https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings)
- [Launch the default app for a URI](https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-default-app)
- [Using ms-windows-store URIs](https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-store-app)
- [Reserved URI scheme names](https://learn.microsoft.com/en-us/windows/uwp/launch-resume/reserved-uri-scheme-names)
- [Shell namespace introduction](https://learn.microsoft.com/en-us/windows/win32/shell/namespace-intro)
- [Find AUMID for packaged apps](https://learn.microsoft.com/en-us/windows/configuration/store/find-aumid)
- [App execution alias extensions](https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/desktop-to-uwp-extensions)

---

## Agent Quick Reference

| Goal | Correct pattern | Wrong pattern |
|------|-----------------|---------------|
| Open Settings page | `cmd /c start ms-settings:display` | `Start-Process ms-settings:display` (no `-UseShellExecute`) |
| Open shell folder | `Start-Process explorer.exe 'shell:Downloads'` | `Start-Process shell:Downloads` |
| Open packaged app by AUMID | `explorer.exe "shell:AppsFolder\<AUMID>"` | Guessing `.exe` path under `WindowsApps` |
| Open protocol URL | `ProcessStartInfo` with `UseShellExecute = $true` | `Invoke-Item ms-settings:...` (PowerShell treats `:` as drive) |
| Open Edge to URL | `microsoft-edge:https://example.com` via ShellExecute | `Start-Process microsoft-edge:...` without ShellExecute |

**Rule of thumb:** URI schemes and `shell:` paths are **not executables**. They require the Windows shell resolver (`ShellExecute`, `cmd start`, or `explorer.exe` as host).

---

## 1. ms-settings: URI Scheme

`ms-settings:` is Windows Settings' internal navigation system. Each page has a stable slug after the colon. Group Policy, Intune, and privacy-aware apps all use the same URIs.

### How to launch

```powershell
# Preferred — works in cmd, Run (Win+R), Explorer address bar, and agents
cmd /c start ms-settings:display

# PowerShell — must use ShellExecute
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'ms-settings:bluetooth'
$psi.UseShellExecute = $true
[System.Diagnostics.Process]::Start($psi) | Out-Null

# Python (ctypes / subprocess)
# subprocess.run(['cmd', '/c', 'start', 'ms-settings:privacy-microphone'])
```

```python
# Orynn-friendly one-liner
import subprocess
def open_settings(page: str = "") -> None:
    uri = f"ms-settings:{page}" if page else "ms-settings:"
    subprocess.run(["cmd", "/c", "start", "", uri], shell=False)
```

### Build variance and discovery

Microsoft documents the most common pages but **does not publish a complete static list** — new pages ship with Windows updates. On this machine, scanning `C:\Windows\ImmersiveControlPanel\SystemSettings.dll` (Unicode strings) found **265** distinct `ms-settings:` slugs.

To enumerate on any machine:

```powershell
$bytes = [IO.File]::ReadAllBytes('C:\Windows\ImmersiveControlPanel\SystemSettings.dll')
$utf16  = [Text.Encoding]::Unicode.GetString($bytes)
[regex]::Matches($utf16, 'ms-settings:[a-zA-Z0-9\-\.]+') |
  ForEach-Object { $_.Value } | Sort-Object -Unique
```

Microsoft also publishes [Get-MSSettingsURIs.ps1](https://techcommunity.microsoft.com/blog/coreinfrastructureandsecurityblog/understanding-windows-settings-uris-and-how-to-use-them-in-enterprise-environmen/4481486) for enterprise discovery.

### Curated ms-settings catalog (40+ pages)

Grouped for agent routing. Pages marked *(conditional)* require hardware, SKU, or policy.

#### System & display

| URI | Description |
|-----|-------------|
| `ms-settings:` | Settings home |
| `ms-settings:about` | Device name, Windows version, activation summary |
| `ms-settings:display` | Brightness, resolution, scale, multiple monitors |
| `ms-settings:display-advanced` | Advanced display (HDR, refresh rate) *(conditional)* |
| `ms-settings:display-advancedgraphics` | Per-app GPU preference |
| `ms-settings:nightlight` | Night light schedule and intensity |
| `ms-settings:screenrotation` | Display orientation |
| `ms-settings:powersleep` | Screen timeout, sleep, lid close behavior |
| `ms-settings:clipboard` | Clipboard history, sync across devices |
| `ms-settings:multitasking` | Snap layouts, Alt+Tab, virtual desktops |
| `ms-settings:quiethours` | Focus assist / Do Not Disturb |
| `ms-settings:project` | Projecting to this PC (Miracast receiver) |
| `ms-settings:crossdevice` | Phone Link / cross-device experiences |
| `ms-settings:remotedesktop` | Remote Desktop client settings |
| `ms-settings:presence` | Presence sensing *(Win11 22H2+)* |
| `ms-settings:energyrecommendations` | Energy recommendations *(Win11 22H2+)* |

#### Sound

| URI | Description |
|-----|-------------|
| `ms-settings:sound` | Output/input device selection, volume |
| `ms-settings:sound-devices` | All sound devices list |
| `ms-settings:apps-volume` | Per-app volume mixer |
| `ms-settings:sound-defaultoutputproperties` | Default speaker properties |
| `ms-settings:sound-defaultinputproperties` | Default microphone properties |

#### Storage & disks

| URI | Description |
|-----|-------------|
| `ms-settings:storagesense` | Storage overview, cleanup |
| `ms-settings:storagepolicies` | Storage Sense automation rules |
| `ms-settings:storagerecommendations` | Storage cleanup suggestions |
| `ms-settings:disksandvolumes` | Disk management, volumes |
| `ms-settings:savelocations` | Default save locations for documents, etc. |

#### Battery *(tablets/laptops only)*

| URI | Description |
|-----|-------------|
| `ms-settings:batterysaver` | Battery saver toggle |
| `ms-settings:batterysaver-settings` | Battery saver thresholds |
| `ms-settings:batterysaver-usagedetails` | Per-app battery usage |

#### Network & internet

| URI | Description |
|-----|-------------|
| `ms-settings:network-status` | Network & internet landing |
| `ms-settings:network-wifi` | Wi-Fi networks *(requires adapter)* |
| `ms-settings:network-wifisettings` | Manage known Wi-Fi networks |
| `ms-settings:network-ethernet` | Ethernet adapter settings |
| `ms-settings:network-vpn` | VPN connections |
| `ms-settings:network-mobilehotspot` | Mobile hotspot |
| `ms-settings:network-proxy` | Proxy configuration |
| `ms-settings:network-airplanemode` | Airplane mode |
| `ms-settings:network-cellular` | Cellular & SIM *(mobile devices)* |
| `ms-settings:network-advancedsettings` | Advanced network settings |
| `ms-settings:wifi-provisioning` | Wi-Fi provisioning packages |

#### Bluetooth & devices

| URI | Description |
|-----|-------------|
| `ms-settings:bluetooth` | Bluetooth pairing and devices |
| `ms-settings:connecteddevices` | Printers, mice, other peripherals |
| `ms-settings:printers` | Printers & scanners |
| `ms-settings:usb` | USB device notifications |
| `ms-settings:mousetouchpad` | Mouse and touchpad settings |
| `ms-settings:devices-touchpad` | Touchpad-only page *(if hardware present)* |
| `ms-settings:typing` | Typing and keyboard settings |
| `ms-settings:pen` | Pen & Windows Ink |
| `ms-settings:autoplay` | AutoPlay defaults for removable media |
| `ms-settings:camera` | Camera settings *(Win11+)*; append `?cameraId=<id>` for specific camera |
| `ms-settings:mobile-devices` | Phone Link / mobile devices |

#### Apps

| URI | Description |
|-----|-------------|
| `ms-settings:appsfeatures` | Installed apps list |
| `ms-settings:appsfeatures-app` | Per-app advanced options; append `?<PackageFamilyName>` |
| `ms-settings:defaultapps` | Default app assignments |
| `ms-settings:startupapps` | Startup applications |
| `ms-settings:optionalfeatures` | Optional Windows features (WSL, Hyper-V, etc.) |
| `ms-settings:appsforwebsites` | Apps for websites associations |
| `ms-settings:videoplayback` | Video playback HDR settings |
| `ms-settings:maps` | Offline maps |
| `ms-settings:developers` | Developer mode, device portal |

**Default app deep link (Win11 21H2 CU+):**

```
ms-settings:defaultapps?registeredAUMID=<uri-escaped-aumid>
ms-settings:defaultapps?registeredAppMachine=<uri-escaped-name>
ms-settings:defaultapps?registeredAppUser=<uri-escaped-name>
```

#### Personalization

| URI | Description |
|-----|-------------|
| `ms-settings:personalization` | Personalization category |
| `ms-settings:personalization-background` | Desktop background |
| `ms-settings:personalization-colors` | Accent colors, transparency |
| `ms-settings:colors` | Alias for color settings |
| `ms-settings:themes` | Theme selection |
| `ms-settings:taskbar` | Taskbar behavior and icons |
| `ms-settings:personalization-start` | Start menu layout |
| `ms-settings:lockscreen` | Lock screen wallpaper |
| `ms-settings:fonts` | Font management |
| `ms-settings:personalization-lighting` | Dynamic Lighting (RGB peripherals) |
| `ms-settings:personalization-textinput` | Text input / touch keyboard |

#### Privacy & security

| URI | Description |
|-----|-------------|
| `ms-settings:privacy` | Privacy & security landing |
| `ms-settings:privacy-general` | General privacy |
| `ms-settings:privacy-location` | Location access |
| `ms-settings:privacy-microphone` | Microphone access |
| `ms-settings:privacy-webcam` | Camera access |
| `ms-settings:privacy-contacts` | Contacts access |
| `ms-settings:privacy-calendar` | Calendar access |
| `ms-settings:privacy-notifications` | Notification access |
| `ms-settings:privacy-speech` | Speech recognition |
| `ms-settings:privacy-speechtyping` | Inking & typing personalization |
| `ms-settings:privacy-broadfilesystemaccess` | Broad file system access |
| `ms-settings:privacy-appdiagnostics` | App diagnostics |
| `ms-settings:windowsdefender` | Windows Security hub |
| `ms-settings:signinoptions` | Sign-in options (PIN, Hello, password) |
| `ms-settings:activation` | Windows activation |
| `ms-settings:deviceencryption` | BitLocker / device encryption |

#### Gaming

| URI | Description |
|-----|-------------|
| `ms-settings:gaming-gamebar` | Xbox Game Bar |
| `ms-settings:gaming-gamedvr` | Captures and background recording |
| `ms-settings:gaming-gamemode` | Game Mode |
| `ms-settings:quietmomentsgame` | Full-screen game notifications |

#### Time, language, accessibility

| URI | Description |
|-----|-------------|
| `ms-settings:dateandtime` | Date, time, time zone |
| `ms-settings:regionlanguage` | Region, language, keyboard layouts |
| `ms-settings:speech` | Speech language and recognition |
| `ms-settings:easeofaccess-display` | Accessibility display |
| `ms-settings:easeofaccess-narrator` | Narrator screen reader |
| `ms-settings:easeofaccess-magnifier` | Magnifier |
| `ms-settings:easeofaccess-highcontrast` | High contrast themes |
| `ms-settings:easeofaccess-keyboard` | On-screen keyboard, sticky keys |

#### Update & recovery

| URI | Description |
|-----|-------------|
| `ms-settings:windowsupdate` | Windows Update |
| `ms-settings:windowsupdate-optionalupdates` | Optional/driver updates |
| `ms-settings:windowsupdate-history` | Update history |
| `ms-settings:windowsupdate-activehours` | Active hours for restarts |
| `ms-settings:delivery-optimization` | Delivery Optimization (P2P updates) |
| `ms-settings:recovery` | Reset PC, advanced startup |
| `ms-settings:troubleshoot` | Troubleshooters |
| `ms-settings:backup` | Opens Sync in Win11 *(backup page removed)* |

#### Accounts & workplace

| URI | Description |
|-----|-------------|
| `ms-settings:yourinfo` | Your Microsoft account info |
| `ms-settings:emailandaccounts` | Email & app accounts |
| `ms-settings:otherusers` | Family & other users |
| `ms-settings:workplace` | Access work or school account |
| `ms-settings:sync` | Sync your settings |

---

## 2. Other ms-* Protocols

Beyond Settings, Windows registers many `ms-*` schemes for built-in apps and flyouts. These are **reserved system schemes** (see [reserved URI list](https://learn.microsoft.com/en-us/windows/uwp/launch-resume/reserved-uri-scheme-names)).

### System & shell flyouts

| Protocol | Opens | Notes |
|----------|-------|-------|
| `ms-actioncenter:` | Quick Settings / Notification Center | Win10 name; Action Center |
| `ms-availablenetworks:` | Wi-Fi network flyout | Quick network picker |
| `ms-screenclip:` | Snipping Tool (screen capture) | Win11 Snip; also `ms-screenclip://capture/...` |
| `ms-screensketch:` | Snip & Sketch legacy alias | Deprecated on Win11 |
| `ms-inputapp:` | Touch keyboard / input panel | |
| `ms-settings-displays-topology:projection` | Project / display topology | Cast screen |

### Microsoft apps

| Protocol | App | Example |
|----------|-----|---------|
| `ms-windows-store:` | Microsoft Store | `ms-windows-store://home/` |
| `ms-contact-support:` | Get Help | Launches support app |
| `microsoft-edge:` | Microsoft Edge | `microsoft-edge:https://example.com` |
| `calculator:` | Calculator | Opens Calculator |
| `ms-photos:` | Photos | `ms-photos:` |
| `outlookmail:` | Mail (legacy UWP) | |
| `outlookcal:` | Calendar | |
| `ms-clock:` | Alarms & Clock | |
| `microsoft.windows.camera:` | Camera | |
| `onenote:` | OneNote | |
| `windowsdefender:` | Windows Security | |
| `feedback-hub:` | Feedback Hub | |
| `ms-get-started:` | Tips / Get Started | |
| `bingmaps:` | Maps | |
| `msnweather:` / `bingweather:` | Weather | |
| `xbox:` | Xbox app | `xbox-settings:`, `xbox-network:` |

### ms-windows-store: deep links

| URI | Action |
|-----|--------|
| `ms-windows-store://home/` | Store home |
| `ms-windows-store://search/?query=OneNote` | Search |
| `ms-windows-store://pdp/?ProductId=9WZDNCRFJ3P2` | Product page by Store ID |
| `ms-windows-store://downloadsandupdates` | Updates & downloads |
| `ms-windows-store://mylibrary` | Library |
| `ms-windows-store://publisher/?name=Microsoft%20Corporation` | Publisher search |
| `ms-windows-store://assoc/?FileExt=pdf` | Apps for `.pdf` |
| `ms-windows-store://assoc/?Protocol=ms-word` | Apps for protocol |

### Packaged-app protocol pattern

Many Store/UWP apps register `PackageFamilyName:` or branded schemes (e.g. `com.microsoft.3dviewer:`). Discover per-app:

```powershell
Get-StartApps                          # Name + AppID (AUMID)
Get-AppxPackage | Select Name, PackageFamilyName
```

Or search registry:

```powershell
Get-ChildItem 'HKCU:\Software\Classes' |
  Where-Object { $_.PSChildName -match '^[a-z]' } |
  ForEach-Object {
    $proto = (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).'URL Protocol'
    if ($proto -ne $null) { $_.PSChildName }
  } | Sort-Object
```

---

## 3. shell: Namespace

The Windows shell namespace is a unified tree of **physical folders** (Downloads) and **virtual folders** (AppsFolder, Recycle Bin). Agents use `shell:` paths to open locations without hard-coding user profile paths.

### Critical: shell is NOT a URI protocol

`shell:` is **not** registered in `HKCR` as a URL protocol. It is resolved by Explorer.

| Works | Fails |
|-------|-------|
| `explorer.exe shell:Downloads` | `Start-Process shell:Downloads` |
| `cmd /c start shell:AppsFolder` | `ProcessStartInfo.FileName = 'shell:Downloads'` without explorer |
| Run dialog (Win+R): `shell:Recent` | Treating `shell:` like `ms-settings:` in bare `Start-Process` |

### Launch patterns

```powershell
# Open folder in Explorer
Start-Process explorer.exe 'shell:Downloads'

# Open virtual AppsFolder (enumerate AUMIDs)
Start-Process explorer.exe 'shell:AppsFolder'

# Launch packaged app by AUMID from AppsFolder namespace
Start-Process explorer.exe 'shell:AppsFolder\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App'

# COM enumeration (headless agent use)
$shell = New-Object -ComObject Shell.Application
$folder = $shell.NameSpace('shell:AppsFolder')
$folder.Items() | ForEach-Object { $_.Name; $_.Path } | Select-Object -First 10
```

### Curated shell: shortcuts

| Command | Opens |
|---------|-------|
| `shell:Desktop` | User desktop folder |
| `shell:Downloads` | `%UserProfile%\Downloads` |
| `shell:Personal` | Documents |
| `shell:My Pictures` | Pictures |
| `shell:My Music` | Music |
| `shell:My Video` | Videos |
| `shell:AppData` | `%AppData%` (Roaming) |
| `shell:Local AppData` | `%LocalAppData%` |
| `shell:Profile` | User profile root |
| `shell:Programs` | Start Menu → Programs |
| `shell:Startup` | User Startup folder |
| `shell:Common Startup` | All-users Startup |
| `shell:Administrative Tools` | Windows Tools |
| `shell:ControlPanelFolder` | Control Panel (all items) |
| `shell:ConnectionsFolder` | Network Connections |
| `shell:PrintersFolder` | Printers |
| `shell:RecycleBinFolder` | Recycle Bin |
| `shell:Recent` | Recent files |
| `shell:SendTo` | Send To menu folder |
| `shell:Fonts` | `%WinDir%\Fonts` |
| `shell:ProgramFiles` | Program Files |
| `shell:ProgramFilesX86` | Program Files (x86) |
| `shell:AppsFolder` | Virtual: all installed apps |
| `shell:Application Shortcuts` | `%LocalAppData%\Microsoft\Windows\Application Shortcuts` |
| `shell:OneDrive` | OneDrive folder *(if configured)* |
| `shell:Libraries` | Libraries |
| `shell:NetworkPlacesFolder` | Network |
| `shell:MyComputerFolder` | This PC |

### GUID form

Equivalent to friendly names; useful when name is ambiguous:

```
shell:::{4234d49b-0245-4df3-b780-3893943456e1}   # Applications / AppsFolder
shell:::{22877a6d-37a1-461a-91b0-dbda5aaebc99}   # Recent Places
shell:::{3080F90D-D7AD-11D9-BD98-0000947B0237}   # Minimize all windows (special)
```

### Discovery

Shell folder names are stored as registry `Name` values:

```powershell
Get-ChildItem 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FolderDescriptions' |
  ForEach-Object {
    $p = Get-ItemProperty $_.PSPath
    [pscustomobject]@{ Shell = "shell:$($p.Name)"; GUID = $_.PSChildName }
  } | Where-Object Shell -ne 'shell:' | Sort-Object Shell
```

**Reference:** [KNOWNFOLDERID](https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid)

### Agent caveat: custom shell / kiosk mode

On machines using Shell Launcher V2 with a custom shell, `shell:AppsFolder` may only list UWP apps and miss newly installed Win32 apps until Explorer shell is initialized. Prefer `Get-StartApps` or registry AUMID queries in those environments.

---

## 4. Custom Protocol Handlers

Third-party and system apps register URI schemes under `HKEY_CLASSES_ROOT\<scheme>` (or `HKCU\Software\Classes`) with a `URL Protocol` string value and `shell\open\command` pointing to an executable.

### Registration anatomy (Win32)

```
HKEY_CLASSES_ROOT\spotify
  (Default) = "URL:spotify"
  URL Protocol = ""
  shell\open\command
    (Default) = "C:\...\Spotify.exe" "%1"
```

Packaged (UWP/MSIX) apps declare `windows.protocol` in the app manifest instead.

### Tested on this machine (2026-06-22)

| Protocol | Registered | ShellExecute launch | Agent notes |
|----------|------------|---------------------|-------------|
| `ms-settings:` | Yes | OK | Use `cmd /c start` or `UseShellExecute` |
| `microsoft-edge:` | Yes | OK | Pass full URL: `microsoft-edge:https://...` |
| `calculator:` | Yes | OK | Opens Calculator |
| `ms-windows-store:` | Yes | OK | Append path: `ms-windows-store://home/` |
| `ms-contact-support:` | Yes | OK | Get Help app |
| `ms-screenclip:` | Yes | OK | Snipping Tool |
| `ms-availablenetworks:` | Yes | OK | Wi-Fi flyout |
| `mailto:` | Yes | OK | Opens default mail client |
| `http:` / `https:` | Yes | OK | Default browser |
| `spotify:` | Yes | OK | Requires Spotify installed |
| `steam:` | Yes (registry) | **FAIL** | Registry present but Steam not installed — handler missing |
| `vscode:` | Yes | OK | VS Code deep links |
| `cursor:` | Yes | OK | Cursor IDE deep links |
| `discord:` | Yes | OK | Discord invite/channel links |
| `tel:` | Yes | OK | Phone dialer |
| `slack:` | No | N/A | Not registered unless Slack installed |
| `shell:` | No | N/A | Not a protocol — use Explorer |

**Common failure modes for agents:**
1. App not installed → registry may exist from leftover installer or protocol reserved but handler exe missing (`steam:` case).
2. `Start-Process <uri>` without `-UseShellExecute` → "system cannot find the file".
3. `Invoke-Item ms-settings:foo` → PowerShell parses `ms-settings` as a drive name.
4. Multiple handlers for same scheme → Windows shows "Open with" picker (blocks unattended automation).
5. Protocol disabled via policy or app execution alias toggle.

### Useful third-party schemes (when app installed)

| Scheme | App |
|--------|-----|
| `steam:` / `steam://` | Steam |
| `spotify:` | Spotify |
| `zoommtg:` | Zoom meetings |
| `slack:` | Slack |
| `discord:` | Discord |
| `tg:` | Telegram |
| `vscode:` / `vscode-insiders:` | Visual Studio Code |
| `cursor:` | Cursor |
| `figma:` | Figma desktop |
| `notion:` | Notion |

---

## 5. App Execution Aliases vs Packaged vs Win32

### Three ways Windows resolves "run this app"

| Mechanism | Example | How it works |
|-----------|---------|--------------|
| **Win32 exe / App Paths** | `notepad.exe`, `regedit.exe` | `HKLM\...\App Paths\<name>.exe` or PATH |
| **App execution alias** | `python.exe`, `wt.exe`, `msedge.exe` | Stub in `%LocalAppData%\Microsoft\WindowsApps\` → packaged app |
| **AUMID / protocol** | `calculator:`, `shell:AppsFolder\...!App` | Shell activation of MSIX/UWP package |

### App execution aliases

- Stubs live in `%LOCALAPPDATA%\Microsoft\WindowsApps\` (also on user PATH).
- Declared in package manifest: `windows.appExecutionAlias` with `Alias="name.exe"`.
- User toggles: **Settings → Apps → Advanced app settings → App execution aliases**.
- **Conflict risk:** Multiple apps can register `python.exe` — only one alias should be enabled.
- Agents should check alias state before assuming `python`/`node`/`code` resolve to expected binaries:

```powershell
Get-Command python -ErrorAction SilentlyContinue | Select Source
Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WindowsApps\*.exe" | Select Name
```

### Packaged (UWP / MSIX) apps

- Install under `C:\Program Files\WindowsApps\` (versioned paths — **do not hard-code**).
- Launch via **AUMID**: `PackageFamilyName!ApplicationId`
- Discover: `Get-StartApps`, `shell:AppsFolder`, or `Get-AppxPackage`
- Support **protocol activation** (`calculator:`) and **app execution aliases**

```powershell
# List Start menu apps with AUMIDs
Get-StartApps | Where-Object Name -match 'Calculator'

# Launch by AUMID
explorer.exe "shell:AppsFolder\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"
```

### Win32 (classic desktop) apps

- Launch by full path, `App Paths`, or Start Menu shortcut `.lnk`.
- **No AUMID** unless also packaged as MSIX.
- May register custom protocols in HKCR.
- Prefer `where.exe <name>` or shortcut target over guessing `Program Files` paths.

### Decision tree for agents

```
Need to open X?
├─ Is it a Settings page? → ms-settings:<slug>
├─ Is it a shell folder? → explorer.exe shell:<name>
├─ Is it a built-in Store app? → Get-StartApps / protocol (calculator:)
├─ Is it a third-party deep link? → <scheme>:<path> via ShellExecute (verify installed)
└─ Is it a classic desktop app? → exe path, App Paths, or Start Menu shortcut
```

---

## 6. PowerShell Launch Patterns

### Pattern matrix

```powershell
# ── URI schemes (ms-settings, mailto, microsoft-edge, calculator, etc.) ──

# A) cmd start — most reliable for agents
cmd /c start "" "ms-settings:privacy-microphone"
cmd /c start "" "microsoft-edge:https://example.com"
cmd /c start "" "mailto:user@example.com"

# B) .NET ShellExecute
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'ms-settings:display'
$psi.UseShellExecute = $true
[void][System.Diagnostics.Process]::Start($psi)

# C) Start-Process with explicit ShellExecute (PS 6+)
Start-Process 'ms-settings:bluetooth' -UseShellExecute

# ── shell: folders ──

Start-Process explorer.exe 'shell:Downloads'
Start-Process explorer.exe 'shell:AppsFolder'
cmd /c start shell:Recent

# ── Packaged app by AUMID ──

$aumid = 'Microsoft.WindowsCalculator_8wekyb3d8bbwe!App'
Start-Process explorer.exe "shell:AppsFolder\$aumid"

# ── Win32 exe (direct) ──

Start-Process 'C:\Windows\System32\notepad.exe'
Start-Process notepad   # resolves via PATH / App Paths

# ── Avoid ──

Start-Process 'ms-settings:display'           # FAIL: no UseShellExecute
Start-Process 'shell:Downloads'               # FAIL: shell is not an exe
Invoke-Item 'ms-settings:display'               # FAIL: drive parsing
```

### Python wrapper for Orynn

```python
import subprocess
import ctypes
from ctypes import wintypes

def shell_execute(uri: str) -> bool:
    """Launch any URI or shell path via Windows ShellExecute."""
    if uri.lower().startswith("shell:"):
        return subprocess.run(
            ["explorer.exe", uri], check=False
        ).returncode == 0
  # URIs: ms-settings, mailto, https, custom protocols
    return subprocess.run(
        ["cmd", "/c", "start", "", uri], shell=False
    ).returncode == 0

def open_settings(page: str = "") -> bool:
    uri = f"ms-settings:{page}" if page else "ms-settings:"
    return shell_execute(uri)

def launch_aumid(aumid: str) -> bool:
    return subprocess.run(
        ["explorer.exe", f"shell:AppsFolder\\{aumid}"], check=False
    ).returncode == 0
```

### Error handling for agents

```powershell
function Invoke-OrynnUri {
    param([Parameter(Mandatory)][string]$Uri)
    try {
        if ($Uri -like 'shell:*') {
            Start-Process explorer.exe $Uri
        } else {
            $psi = New-Object System.Diagnostics.ProcessStartInfo
            $psi.FileName = $Uri
            $psi.UseShellExecute = $true
            $null = [System.Diagnostics.Process]::Start($psi)
        }
        return @{ ok = $true; uri = $Uri }
    } catch {
        return @{ ok = $false; uri = $Uri; error = $_.Exception.Message }
    }
}
```

---

## 7. Orynn Integration Recommendations

1. **Add `open_uri` tool** with the `shell:` vs URI branch above — never raw `Start-Process $uri`.
2. **Expand settings catalog** beyond the 7 built-in voice launches; map intent → `ms-settings:` slug.
3. **Prefer `Get-StartApps`** over clicking Start Menu for packaged app resolution.
4. **Cache AUMID lookups** per machine; paths under `WindowsApps` are versioned.
5. **Verify protocol before deep link** — check `HKCU:\Software\Classes\<scheme>` or `Test-Path` registry.
6. **Fall back to UIA** when URI opens wrong handler (multi-handler picker) or page slug missing on older builds.

---

## Sources

| Source | URL |
|--------|-----|
| Launch Windows Settings | https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings |
| Launch default app for URI | https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-default-app |
| ms-windows-store URIs | https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-store-app |
| Reserved URI schemes | https://learn.microsoft.com/en-us/windows/uwp/launch-resume/reserved-uri-scheme-names |
| Shell namespace | https://learn.microsoft.com/en-us/windows/win32/shell/namespace-intro |
| Find AUMID | https://learn.microsoft.com/en-us/windows/configuration/store/find-aumid |
| App execution aliases | https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/desktop-to-uwp-extensions |
| Enterprise URI discovery | https://techcommunity.microsoft.com/blog/coreinfrastructureandsecurityblog/understanding-windows-settings-uris-and-how-to-use-them-in-enterprise-environmen/4481486 |
| Shell folder shortcuts (community) | https://ss64.com/nt/shell.html |
