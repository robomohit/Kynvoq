# Windows Automation Research — Index

Research for Orynn's scalable voice + desktop orchestration (Gemini Live front desk + UIA-first back-office agent).

**Start here:** [00-master-strategy.md](./00-master-strategy.md)

---

## Documents in this folder

| File | Description |
|------|-------------|
| [00-master-strategy.md](./00-master-strategy.md) | **Master strategy** — architecture, decision tree, 3-layer model (launch/navigate/act), memory/workflows/playbooks, method table, anti-patterns, competitor analysis, roadmap |
| [03-universal-launch.md](./03-universal-launch.md) | **Universal launch** — Win+Search, `start`/AUMID/`.lnk`, discovery APIs, `_KNOWN_LAUNCH_APPS` / `detect_app_launch_intent`, scaling to hundreds of apps |
| [05-keyboard-input.md](./05-keyboard-input.md) | **Keyboard & input** — SendInput, pyautogui, UIA SendKeys, shortcuts, command palettes |
| [06-electron-chromium.md](./06-electron-chromium.md) | **Electron / Chromium** — unlock strategies, `--force-renderer-accessibility`, app list |
| [07-app-framework-taxonomy.md](./07-app-framework-taxonomy.md) | **App framework taxonomy** — Win32, UWP, Electron, Office classification |
| [08-powershell-system-no-ui.md](./08-powershell-system-no-ui.md) | **PowerShell system (no UI)** — WMI/CIM, registry, system state without clicking |
| [INDEX.md](./INDEX.md) | This index |

---

## Related documents (parent `docs/`)

| File | Description |
|------|-------------|
| [../windows-automation-research.md](../windows-automation-research.md) | **Methods deep dive** — UIA, ms-settings/shell/AUMID catalogs, OCR/grid, Electron unlock, app-class table, Orynn tool inventory, gap analysis, sources |
| [../BENCHMARKS.md](../BENCHMARKS.md) | UIA vs screenshot workflow timings and pass rates |
| [../ROADMAP.md](../ROADMAP.md) | Product roadmap (UIA-first, trust, benchmarks, installer) |
| [../DEMO_SCRIPT.md](../DEMO_SCRIPT.md) | Demo flows for voice + desktop tasks |

---

## Code map (implementation)

| Area | Primary files |
|------|---------------|
| Live orchestration & tools | `app/widget/gemini_live.py`, `app/widget/textbox_overlay.py` |
| Back-office agent | `app/agent.py`, `app/tools.py` |
| UIA / desktop primitives | `app/widget/desktop_features.py`, `app/tools.py` |
| Lazy playbooks | `app/adaptive_windows.py`, `adaptive_windows_profiles.json` |
| Vision grid fallback | `app/grid_locate.py` |
| Connector skills | `app/connectors.py`, `app/background_browser.py` |
| Saved workflows | `app/workflows.py` |
| Live tests | `tests/test_gemini_live.py`, `tests/test_live_robustness.py` |

---

## Topic quick links

| Topic | Where |
|-------|-------|
| chat vs look_at_screen vs desktop_control vs run_terminal vs start_desktop_task | [00-master-strategy.md §2](./00-master-strategy.md#2-orchestration-decision-tree) |
| Launch / navigate / act | [00-master-strategy.md §3](./00-master-strategy.md#3-universal-three-layer-model) · [03-universal-launch.md](./03-universal-launch.md) |
| `detect_app_launch_intent` / voice fast-path | [03-universal-launch.md §9](./03-universal-launch.md#9-orynn-implementation--current-state) |
| AUMID / `Get-StartApps` / `.lnk` index | [03-universal-launch.md §6–7](./03-universal-launch.md#6-discovery-apis-whereexe-get-startapps-winget-list) |
| Memory, workflows, lazy playbooks | [00-master-strategy.md §4](./00-master-strategy.md#4-memory-workflows-and-lazy-playbooks) |
| Method comparison table | [00-master-strategy.md §5](./00-master-strategy.md#5-method-comparison--master-table) · [deep dive §Method Comparison](../windows-automation-research.md#method-comparison) |
| Anti-patterns | [00-master-strategy.md §6](./00-master-strategy.md#6-anti-patterns) |
| Clicky / Anthropic / Power Automate | [00-master-strategy.md §7](./00-master-strategy.md#7-competitor-patterns) |
| ms-settings & shell URIs (full tables) | [../windows-automation-research.md §2](../windows-automation-research.md#2-special-windows-mechanisms) |
| Electron app list & unlock | [../windows-automation-research.md §7](../windows-automation-research.md#7-electron-apps--list--unlock-strategies) |

---

*Last updated: 2026-06-22*
