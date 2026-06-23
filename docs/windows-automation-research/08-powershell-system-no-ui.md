# 08 — Non-UI System Automation on Windows (No Clicking)

**Date:** 2026-06-22  
**Scope:** Headless Windows administration via shell, WMI/CIM, registry, package managers, services, and scheduled tasks — for Orynn's `run_terminal` path and back-office `run_command`.  
**Related:** `docs/windows-automation-research.md`, `app/tools.py` (`run_command`), `app/widget/gemini_live.py` (`run_terminal`), `app/widget/textbox_overlay.py` (`_live_run_terminal`)

---

## Executive Summary

Most Windows system tasks do **not** require UI Automation, screenshots, or the desktop agent. They are faster, more reliable, and easier to verify when executed as **single shell commands** or short PowerShell one-liners. Orynn's `run_command` already runs commands via `subprocess` with `shell=True`, a 120-second timeout, POSIX→Windows translation (`ls`→`dir`, `cat`→`type`), and the same `SafetyManager` guard used by Live's `run_terminal`.

**Rule of thumb for Orynn Live routing:**

| User intent | Route | Why |
|-------------|-------|-----|
| One command, stdout answer | `run_terminal` | Synchronous output, voice-friendly, cancellable |
| Open app + click/type through UI | `start_desktop_task` | Needs UIA, focus, multi-step |
| Install/uninstall/kill service | `run_terminal` (with consent) | Destructive; no UI needed |
| "Open Settings and toggle Bluetooth" | `run_terminal` for `start ms-settings:bluetooth` | URI launch, not navigation |
| "Fill out this web form" | `start_desktop_task` | UI interaction |
| Long build / watch logs | `start_desktop_task` or streaming `run_command` | Exceeds Live's 120s sync window |

**Top three findings (see §9):** PowerShell cmdlets beat legacy `wmic`/`netsh` for structured output; registry writes are high-risk and rarely needed; Live should own all no-UI system queries while the desktop agent should not re-open apps the user already has focused unless the task requires UI proof.

---

## 1. PowerShell Process Management

PowerShell is the preferred automation shell on Windows 10/11. Orynn's `run_command` defaults to `cmd.exe` semantics via `shell=True`; prefix with `powershell -NoProfile -Command "..."` for cmdlet-heavy work.

### 1.1 `Get-Process`

**Purpose:** List running processes, filter by name, inspect CPU/memory, resolve PIDs.

```powershell
# All processes (tabular)
Get-Process | Sort-Object CPU -Descending | Select-Object -First 15 Name, Id, CPU, WS

# By name (supports wildcards)
Get-Process -Name "Code","Cursor" -ErrorAction SilentlyContinue

# Process for a specific window title (indirect)
Get-Process | Where-Object { $_.MainWindowTitle -like '*Notepad*' }

# JSON for machine parsing (good for agent output)
Get-Process notepad | Select-Object Name, Id, Path, StartTime | ConvertTo-Json
```

**vs Task Manager / UI:** Instant, scriptable, no focus steal.  
**vs `tasklist`:** `Get-Process` returns rich objects; `tasklist /FO CSV` is fine for quick checks in `cmd`.

**Orynn notes:**
- Safe for `run_terminal` without consent.
- `Get-Process` does not show elevated details without elevation; some `Path` values are blank for protected processes.
- Prefer name + Id together when recommending `Stop-Process` to avoid killing the wrong instance.

### 1.2 `Start-Process`

**Purpose:** Launch executables with explicit control over window style, arguments, working directory, elevation.

```powershell
# GUI app, normal window
Start-Process notepad.exe

# Hidden / no window (background)
Start-Process powershell.exe -ArgumentList '-NoProfile','-File','C:\scripts\backup.ps1' -WindowStyle Hidden

# Wait for exit and capture exit code
$p = Start-Process -FilePath 'git' -ArgumentList 'status' -WorkingDirectory 'C:\repo' -NoNewWindow -Wait -PassThru
$p.ExitCode

# Run elevated (triggers UAC — user must approve; do NOT automate clicking UAC)
Start-Process powershell.exe -Verb RunAs -ArgumentList '-Command','Get-Service'
```

**vs `start` (cmd):** `start` is fire-and-forget; Orynn's `_launch_gui_command` already uses `Popen` detached for `start calc`-style launches. Use `Start-Process` when you need `-Wait`, `-PassThru`, or `-WindowStyle`.

**Orynn notes:**
- `run_command "start notepad"` → GUI launch path (detached, optional `wait_for_window`).
- `run_terminal "powershell -Command Start-Process notepad -Wait"` → blocks until Notepad closes (usually wrong for voice UX).
- For **opening apps**, prefer `start <exe>` or `start ms-settings:*` via `run_terminal`; reserve `start_desktop_task` when UI steps follow.

### 1.3 `Stop-Process`

**Purpose:** Terminate by name or Id.

```powershell
Stop-Process -Name notepad -Force -ErrorAction SilentlyContinue
Stop-Process -Id 12345 -Force
```

**Safety:** Destructive — can lose unsaved work. Orynn's `_command_needs_consent` treats kill/stop patterns as requiring spoken confirmation before `run_terminal` executes.

**Alternatives:**
- `taskkill /IM notepad.exe /F` — cmd equivalent; same consent gate.
- Graceful close for GUI apps: `Stop-Process` without `-Force` sends close message; many apps prompt to save.

**When NOT to use:** System-critical processes (`csrss`, `winlogon`, `lsass`) — hard-blocked by safety layer. Prefer closing the app window via UI only when the user explicitly wants "click X" behavior.

### 1.4 Process discovery quick reference

| Task | Command |
|------|---------|
| Is X running? | `powershell -Command "(Get-Process -Name X -EA 0).Count -gt 0"` |
| PID of X | `powershell -Command "(Get-Process X).Id"` |
| Kill stuck build | `taskkill /IM node.exe /F` (consent) |
| Child processes | `Get-CimInstance Win32_Process -Filter "ParentProcessId=1234"` |

---

## 2. WMI / CIM (`Win32_*`)

**WMI** (Windows Management Instrumentation) is the legacy umbrella API. **CIM** cmdlets (`Get-CimInstance`) are the modern PowerShell interface — prefer CIM over deprecated `gwmi` and **`wmic`** (removed/disabled on current Windows 11 builds).

### 2.1 Core pattern

```powershell
# Query
Get-CimInstance -ClassName Win32_OperatingSystem |
  Select-Object Caption, Version, BuildNumber, LastBootUpTime, TotalVisibleMemorySize

# Filter (WQL)
Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" |
  Select-Object DeviceID, Size, FreeSpace

# Remote (rare for Orynn; needs WinRM)
Get-CimInstance Win32_BIOS -ComputerName OTHER-PC -Credential $cred
```

### 2.2 High-value `Win32_*` classes

| Class | Use |
|-------|-----|
| `Win32_OperatingSystem` | OS version, uptime, memory |
| `Win32_ComputerSystem` | Manufacturer, model, total RAM, domain |
| `Win32_Processor` | CPU name, cores, clock |
| `Win32_LogicalDisk` | Volumes, free space (local disks: `DriveType=3`) |
| `Win32_PhysicalMemory` | RAM sticks, speed, capacity |
| `Win32_NetworkAdapterConfiguration` | IP enabled adapters, MAC, DHCP (`IPEnabled=TRUE`) |
| `Win32_Product` | Installed MSI products (**slow** — triggers consistency check) |
| `Win32_Service` | Service state (prefer `Get-Service` for local) |
| `Win32_Process` | Process list with command line, parent PID |
| `Win32_StartupCommand` | Legacy startup entries |
| `Win32_UserAccount` | Local accounts (not Azure AD primary) |
| `Win32_BIOS` / `Win32_BaseBoard` | Serial, firmware |
| `Win32_PnPEntity` | Plug-and-play devices (driver issues) |
| `Win32_OptionalFeature` | Windows optional features state |

### 2.3 `Win32_Product` warning

**Never** call `Win32_Product` in a tight loop or on every query — it invokes MSI repair consistency checks and can take minutes. For installed software, use:

```powershell
Get-Package | Select-Object Name, Version, ProviderName
winget list --accept-source-agreements
Get-ItemProperty HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\* |
  Select-Object DisplayName, DisplayVersion, Publisher
```

### 2.4 WMI vs PowerShell native cmdlets

| Need | Prefer | Avoid |
|------|--------|-------|
| Services | `Get-Service`, `Start-Service` | `Win32_Service` unless you need extra fields |
| Disks (simple) | `Get-PSDrive`, `Get-Volume` | WMI for basic free space |
| OS info | `Get-ComputerInfo` (slow but comprehensive) | Parsing `systeminfo` |
| Network config | `Get-NetIPAddress`, `Get-NetAdapter` | `Win32_NetworkAdapterConfiguration` for simple IP/MAC |
| Processes | `Get-Process` | `Win32_Process` when you need CommandLine |

**Orynn routing:** All read-only CIM queries → `run_terminal`. No desktop agent.

---

## 3. Network & System CLI Tools

### 3.1 `ipconfig`

Classic, fast, no elevation for read:

```cmd
ipconfig
ipconfig /all
ipconfig /flushdns
```

`/flushdns` is mutating — consent gate. `/release` and `/renew` are disruptive — consent or block.

**PowerShell equivalents:**

```powershell
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' }
Get-DnsClientCache  # view; Clear-DnsClientCache  # flush
```

### 3.2 `netsh`

Legacy but still installed; some subcommands deprecated in favor of PowerShell networking modules.

| Task | netsh | Modern alternative |
|------|-------|-------------------|
| Show interfaces | `netsh interface show interface` | `Get-NetAdapter` |
| Wi-Fi profiles | `netsh wlan show profiles` | `netsh` still common for WLAN |
| Export Wi-Fi profile | `netsh wlan export profile name=X folder=.` | — |
| Firewall rules | `netsh advfirewall` | `Get-NetFirewallRule` |
| Portproxy | `netsh interface portproxy` | Still netsh |
| HTTP proxy | `netsh winhttp show proxy` | — |

**Orynn:** Read-only `netsh wlan show interfaces` → `run_terminal`. Adding firewall rules or changing WLAN → consent. Prefer **not** to automate Wi-Fi password connect via netsh (stores profiles; security sensitive).

### 3.3 `systeminfo`

```cmd
systeminfo
```

Human-readable dump: OS, hotfixes, network cards, memory. Slow on some machines (boot time calculation). Good for voice summaries; bad for parsing.

**Structured alternative:**

```powershell
Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, OsHardwareAbstractionLayer,
  CsTotalPhysicalMemory, BiosSerialNumber
```

### 3.4 `wmic` — deprecated; use these instead

| Old wmic | Replacement |
|----------|-------------|
| `wmic process list brief` | `Get-Process` or `tasklist` |
| `wmic cpu get name` | `Get-CimInstance Win32_Processor` |
| `wmic diskdrive get size,model` | `Get-PhysicalDisk` |
| `wmic nicconfig get ipaddress` | `Get-NetIPAddress` |
| `wmic startup list` | `Get-CimInstance Win32_StartupCommand` or Task Manager Startup (UI) |
| `wmic qfe list` | `Get-HotFix` |
| `wmic bios get serialnumber` | `(Get-CimInstance Win32_BIOS).SerialNumber` |

On Windows 11 24H2+, `wmic` may be absent — scripts must not depend on it.

### 3.5 Other useful no-UI commands

```cmd
hostname
whoami
whoami /groups
ver
driverquery
schtasks /Query /FO LIST
sc query type= service state= all
powershell -Command "Get-TimeZone"
powershell -Command "(Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime"
```

---

## 4. Registry Automation

The registry is a configuration database, not a UI. Automation is appropriate for **reading** defaults and **idempotent** per-user tweaks; dangerous for **blind writes** to `HKLM` or classes root.

### 4.1 Safe read patterns (PowerShell)

```powershell
# Machine-wide program install location
Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\notepad.exe'

# Current user environment
Get-ItemProperty 'HKCU:\Environment'

# Default browser (check, don't set without consent)
(Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice').ProgId
```

**Orynn:** Read-only registry queries → `run_terminal`, no consent.

### 4.2 When registry writes are appropriate

| Scenario | Example | Risk |
|----------|---------|------|
| Per-user file association (with consent) | `Set-ItemProperty` under `HKCU\...\UserChoice` | Medium — wrong ProgId breaks links |
| Enable developer setting | `HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced` | Low if scoped to HKCU |
| IT-style machine policy | `HKLM:\SOFTWARE\Policies\...` | High — needs admin + consent |
| "Speed up Windows" blog scripts | Mass `HKLM` tweaks | **Block** — unpredictable |
| Uninstall cleanup | Deleting orphan keys | High — can break installers |

### 4.3 When registry automation is dangerous

- **Deleting** `HKLM\SYSTEM`, `SAM`, `SECURITY`, `SOFTWARE\Classes` subtrees
- **Blind .reg imports** from the internet
- **UserChoice hash** manipulation (Windows 11 protects browser defaults with hash validation — direct writes fail or corrupt)
- **Autorun** keys without user awareness (`Run`, `RunOnce`)
- **Elevation-required** keys without explicit user approval

**Orynn policy:** Treat `reg add`, `reg delete`, `Remove-Item` on registry paths, and `reg import` as **destructive** → consent via `_command_needs_consent`. Prefer `start ms-settings:` URIs over registry for user-facing toggles (Bluetooth, microphone, night light).

### 4.4 Registry vs Settings URIs

| User says | Prefer | Not |
|-----------|--------|-----|
| "Open Bluetooth settings" | `start ms-settings:bluetooth` | Registry |
| "What's my default browser?" | Registry read `UserChoice` | Clicking Settings |
| "Disable telemetry" | Explain + Settings URI or Group Policy | Random `HKLM` hacks |

---

## 5. Package Managers: `winget` and Chocolatey

### 5.1 WinGet (built-in on Windows 11, installable on 10)

```powershell
# Search
winget search python

# Install (elevated; may prompt)
winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements

# List installed
winget list

# Upgrade
winget upgrade --all --accept-package-agreements

# Uninstall
winget uninstall --id Microsoft.OneDrive
```

**Flags for automation:**
- `--silent` / `-h` — suppress UI where supported
- `--accept-package-agreements` — avoid interactive prompts
- `-e` — exact match on Id

**Orynn:** Install/uninstall/upgrade → **destructive** → spoken consent + `confirmed: true` on `run_terminal`. Expect UAC for per-machine installs. Long installs may exceed 120s — consider `start_desktop_task` with a single `winget install` step and status polling, or increase timeout for agent-only paths.

### 5.2 Chocolatey (`choco`)

```powershell
choco search nodejs
choco install nodejs-lts -y
choco upgrade all -y
choco uninstall git -y
```

Requires separate Chocolatey installation (admin). `-y` confirms prompts — still treat as destructive in Orynn.

### 5.3 WinGet vs Choco vs UI

| | WinGet | Chocolatey | Store UI |
|--|--------|------------|----------|
| Preinstalled | Often on Win11 | No | Yes |
| Scriptable | Excellent | Excellent | Needs desktop agent |
| Source | MS + community | Community feed | Microsoft Store |
| Elevation | Common | Common | User-driven |

**Orynn routing:** "Install Python" → `run_terminal` with `winget install ...` after consent, **not** `start_desktop_task` opening Store unless winget fails and user prefers GUI.

---

## 6. Scheduled Tasks & Services

### 6.1 Services

**PowerShell (preferred):**

```powershell
Get-Service | Where-Object Status -eq 'Running' | Select-Object Name, DisplayName, Status
Get-Service wuauserv
Start-Service wuauserv    # consent + often admin
Stop-Service wuauserv -Force
Restart-Service spooler
Set-Service -Name X -StartupType Manual
```

**SC.exe (cmd):**

```cmd
sc query wuauserv
sc start wuauserv
sc stop wuauserv
```

**Orynn:** Query → `run_terminal`. Start/stop/restart → consent. Stopping critical services (RPC, EventLog, Winmgmt) should remain blocked or heavily confirmed.

### 6.2 Scheduled Tasks

**PowerShell:**

```powershell
Get-ScheduledTask | Where-Object State -eq 'Ready' | Select-Object TaskName, TaskPath, State
Get-ScheduledTask -TaskName '\Microsoft\Windows\UpdateOrchestrator\Reboot' -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName 'OrynnBackup' -Action $action -Trigger $trigger -User $env:USERNAME
Unregister-ScheduledTask -TaskName 'OrynnBackup' -Confirm:$false
Start-ScheduledTask -TaskName 'OrynnBackup'
```

**Schtasks.exe:**

```cmd
schtasks /Query /FO TABLE
schtasks /Create /TN "OrynnBackup" /TR "powershell.exe -File C:\backup.ps1" /SC DAILY /ST 02:00
schtasks /Delete /TN "OrynnBackup" /F
schtasks /Run /TN "OrynnBackup"
```

**Orynn:** Creating/deleting/running tasks → consent. Querying → safe `run_terminal`.

**vs UI (Task Scheduler):** No clicking through `taskschd.msc` unless user wants to "see" the task — URI: `taskschd.msc` opens MMC (GUI); still no need for desktop agent if only opening the console.

---

## 7. Windows Terminal vs `cmd.exe`

### 7.1 What Orynn actually runs

`app/tools.py` `run_command` uses:

```python
subprocess.run(command, shell=True, capture_output=True, text=True, timeout=120, ...)
```

On Windows, `shell=True` invokes **`cmd.exe /c`** by default — not PowerShell, not Windows Terminal.

**Implications:**
- PowerShell cmdlets require explicit wrapper: `powershell -NoProfile -Command "..."`
- `&&` chaining works on modern cmd (Windows 10+)
- No profile aliases unless you call `powershell`
- UTF-8 output may need `$OutputEncoding` or `chcp 65001` for legacy console apps

### 7.2 Windows Terminal (`wt.exe`)

Windows Terminal is a **host** for tabs (PowerShell, cmd, WSL) — not a replacement for `cmd.exe` semantics.

```cmd
wt -w 0 nt cmd /k "cd /d C:\repo && git status"
wt powershell -NoExit -Command "Get-Process"
```

**Use for Orynn:** Launching a visible terminal for the user (`start wt` or `wt ...`) when they want to **see** a session — optional `start_desktop_task`. **Do not** use `wt` as the backend for captured output — it opens GUI tabs; stdout capture is unreliable for voice readback.

### 7.3 Shell choice guide

| Need | Shell |
|------|-------|
| Fast file listing, `git`, `npm` | cmd (default) or explicit `powershell` |
| WMI/CIM, services, packages | `powershell -NoProfile -Command` |
| User-visible debugging session | `wt` or `start powershell` |
| Legacy batch | cmd |
| Strict execution policy scripts | `powershell -ExecutionPolicy Bypass -File script.ps1` |

### 7.4 POSIX translation (Orynn-specific)

Live often emits Unix habits. `run_command` rewrites simple lone commands:

| Model says | Runs as |
|------------|---------|
| `ls` | `dir` |
| `ls Downloads` | `dir Downloads` |
| `cat file.txt` | `type file.txt` |
| `pwd` | `cd` |
| `which git` | `where git` |

Pipes, redirects, and chains are **not** rewritten — use correct Windows syntax or wrap in PowerShell.

---

## 8. Orynn Live Routing: `run_terminal` vs `start_desktop_task`

### 8.1 Tool contracts (from `gemini_live.py`)

**`run_terminal`:**
- Single shell command; stdout/stderr returned to Live (~1500 chars)
- Short commands: git, dir, versions, pip/npm, reading files via `type`/`Get-Content`
- Catastrophic commands hard-blocked (`SafetyManager`)
- Destructive commands need spoken consent + `confirmed: true`
- Cancellable mid-flight (`_run_cancellable`)
- 120s timeout in underlying `run_command`

**`start_desktop_task`:**
- Full desktop agent: open apps, multi-step goals, UI workflows
- Background execution with `get_companion_status` updates
- UIA-first (`DESKTOP_HARDENING` prompt)
- For long-running or ambiguous UI work

### 8.2 Decision matrix — no-UI system tasks

| User request | Tool | Example command |
|--------------|------|-----------------|
| "What's my IP?" | `run_terminal` | `ipconfig` or `Get-NetIPAddress` |
| "How much disk space left?" | `run_terminal` | `powershell -Command "Get-PSDrive C"` |
| "Is Docker running?" | `run_terminal` | `Get-Process -Name com.docker.backend -EA 0` |
| "Git status" | `run_terminal` | `git status` |
| "List Downloads" | `run_terminal` | `dir %USERPROFILE%\Downloads` |
| "Install Node via winget" | `run_terminal` + consent | `winget install OpenJS.NodeJS.LTS -e` |
| "Kill Firefox" | `run_terminal` + consent | `taskkill /IM firefox.exe /F` |
| "Restart Print Spooler" | `run_terminal` + consent | `Restart-Service spooler` |
| "Open Device Manager" | `run_terminal` | `start devmgmt.msc` |
| "Open Bluetooth settings" | `run_terminal` | `start ms-settings:bluetooth` |
| "Run npm build" (long) | `start_desktop_task` | Agent monitors output / window |
| "Open Excel and chart this" | `start_desktop_task` | COM/UI required |
| "Click OK on that dialog" | `desktop_control` | UI only |
| "Set up my dev environment" | `start_desktop_task` | Multi-step |

### 8.3 When desktop agent should NOT be used

If the entire task can be answered by **one command's stdout**, never spawn the desktop agent. Common mis-routes to fix in prompts:

- "List processes" → `run_terminal`, not Task Manager UI
- "Check Windows version" → `ver` / `Get-ComputerInfo`, not `winver` GUI
- "Flush DNS" → `ipconfig /flushdns` with consent, not navigating Settings
- "Uninstall X" → `winget uninstall` with consent, not Apps & Features clicking

### 8.4 When `run_terminal` is insufficient

| Limitation | Escalate to |
|------------|-------------|
| Needs UAC elevation and user won't see prompt | Explain; user must approve UAC |
| >120 seconds | `start_desktop_task` or streaming agent `run_command_streaming` |
| Multi-step conditional UI | `start_desktop_task` |
| Must verify visual outcome | `look_at_screen` / `capture_window` after command |
| Installer has no silent flag | `start_desktop_task` or user manual step |

### 8.5 Safety alignment

Both paths share `SafetyManager` for `run_command`. Live adds `_command_needs_consent` for destructive-but-not-catastrophic patterns (delete, push, kill, uninstall). System automation must respect:

- **Hard block:** format, diskpart wipe, `rm -rf /`, shutdown/reboot without consent policy
- **Consent:** `Stop-Process`, `taskkill`, `winget uninstall`, `reg delete`, `sc stop`, firewall changes
- **Safe read:** `Get-*`, `query`, `list`, `status`, `ipconfig`, `systeminfo`

### 8.6 Recommended voice mappings (add to Live examples)

```
"how much RAM" → run_terminal: powershell Get-CimInstance Win32_OperatingSystem
"what's using CPU" → run_terminal: Get-Process | Sort CPU -Desc | Select -First 10
"wifi status" → run_terminal: netsh wlan show interfaces
"installed Python?" → run_terminal: winget list --name Python
"restart my PC" → consent + run_terminal OR refuse if policy blocks
"open services" → run_terminal: start services.msc  (GUI MMC, still no desktop agent)
```

---

## 9. Three Key Findings

### Finding 1: PowerShell + CIM replaces `wmic` and most `netsh` queries

Modern Windows automation should default to **`Get-CimInstance`**, **`Get-Service`**, **`Get-NetAdapter`**, and **`Get-Process`** — structured, parseable, and maintained. Legacy `wmic` is deprecated or removed; `systeminfo` and `ipconfig` remain fine for human-readable voice summaries. Orynn should wrap common queries as one-liner `powershell -NoProfile -Command` strings in Live examples to reduce model errors.

### Finding 2: Registry and service writes are rarely the right first move

**Read** registry for diagnostics; **write** only for scoped `HKCU` tweaks with consent. User-facing toggles should use **`ms-settings:` URIs** or **`winget`**, not registry hacks. Starting/stopping services and killing processes are **destructive** — correct for `run_terminal` but always behind spoken consent. Avoid `Win32_Product` entirely in automation paths.

### Finding 3: Live owns headless system work; desktop agent owns UI proof loops

If stdout fully answers the user, route to **`run_terminal`** — faster, cancellable, no focus steal, no UIA flake. Use **`start_desktop_task`** only when the task needs window focus, sequential UI actions, long-running monitored work, or installers without silent flags. Opening MMC/Settings via `start <msc>` or `ms-settings:` is still **`run_terminal`**, not desktop agent — only subsequent clicking inside those windows escalates.

---

## 10. Quick Command Cookbook (copy-paste for agents)

```powershell
# Uptime
powershell -NoProfile -Command "(Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime"

# Disk free (GB)
powershell -NoProfile -Command "Get-PSDrive -PSProvider FileSystem | Select Name,@{N='FreeGB';E={[math]::Round($_.Free/1GB,2)}}"

# Battery (laptops)
powershell -NoProfile -Command "Get-CimInstance Win32_Battery | Select EstimatedChargeRemaining,BatteryStatus"

# Public IP (network)
powershell -NoProfile -Command "(Invoke-RestMethod ipinfo.io/ip)"

# Default gateway
powershell -NoProfile -Command "Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Select NextHop,InterfaceAlias"

# Listening ports
netstat -ano | findstr LISTENING

# Firewall profile status
powershell -NoProfile -Command "Get-NetFirewallProfile | Select Name,Enabled"

# Recent hotfixes
powershell -NoProfile -Command "Get-HotFix | Sort InstalledOn -Desc | Select -First 5 HotFixID,InstalledOn"
```

---

## 11. Sources

| Topic | URL |
|-------|-----|
| Get-Process | https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/get-process |
| Start-Process | https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/start-process |
| Stop-Process | https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/stop-process |
| Get-CimInstance | https://learn.microsoft.com/en-us/powershell/module/cimcmdlets/get-ciminstance |
| Win32_OperatingSystem | https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-operatingsystem |
| WinGet | https://learn.microsoft.com/en-us/windows/package-manager/winget/ |
| Scheduled tasks | https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/ |
| Get-Service | https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/get-service |
| WMIC deprecation | https://learn.microsoft.com/en-us/windows/whats-new/deprecated-features |
| ms-settings URIs | https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings |

---

*Orynn implementation touchpoints: `run_command` / `_windows_translate_command` in `app/tools.py`; Live `run_terminal` in `app/widget/textbox_overlay.py`; routing examples in `app/widget/gemini_live.py` `_default_system_instruction()`.*
