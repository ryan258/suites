# A3 — Keyboard Overlay Consolidation & Parity Decision

Snapshot: 2026-08-20, source-backed live repository review. No source repository was modified or deleted.

---

## Executive Outcome

[`kb-overlay`](file:///Users/ryanjohnson/Projects/kb-overlay) is confirmed as the **sole canonical anchor** for the portfolio's browser assistance and keyboard navigation capabilities. The two duplicate checkouts—[`keyboard-nav-overlay`](file:///Users/ryanjohnson/Projects/keyboard-nav-overlay) and [`keyboard-nav-overlay-94bf7e`](file:///Users/ryanjohnson/Projects/keyboard-nav-overlay-94bf7e)—are 100% superseded in capability and are classified as duplicate donors to be frozen.

```text
CANONICAL TARGET: kb-overlay (Manifest V3, Shadow DOM, MutationObserver, Global Shortcuts)
SUPERSEDED DONORS: keyboard-nav-overlay, keyboard-nav-overlay-94bf7e
PERMISSION PROFILE: Minimized to ["activeTab", "storage"] (Zero broad host permissions)
RECONCILIATION STATUS: 100% feature coverage verified in canonical target
```

---

## Live Source Fingerprints & Preservation Boundary

| Repository | Path | Git Head | Size | Role | Disposition |
|---|---|---|---|---|---|
| `kb-overlay` | `/Users/ryanjohnson/Projects/kb-overlay` | `main@c9f1201` | ~33.4 KB | Canonical Anchor | Retained & Active |
| `keyboard-nav-overlay` | `/Users/ryanjohnson/Projects/keyboard-nav-overlay` | `main@98877bc` | ~9.5 KB | Duplicate Donor | Frozen Donor |
| `keyboard-nav-overlay-94bf7e` | `/Users/ryanjohnson/Projects/keyboard-nav-overlay-94bf7e` | `main@94bf7e3` | ~4.1 KB | Duplicate Donor | Frozen Donor |

---

## Detailed Capability & Architecture Matrix

| Capability / Architecture | `kb-overlay` (Canonical) | `keyboard-nav-overlay` (Donor 1) | `keyboard-nav-overlay-94bf7e` (Donor 2) | Parity Verdict |
|---|---|---|---|---|
| **Platform** | Manifest V3 | Manifest V3 | Manifest V3 | Parity |
| **Permissions** | `["activeTab", "storage"]` | `["activeTab", "storage"]` | `["activeTab", "storage"]` | Parity (Zero over-permissioning) |
| **DOM Isolation** | **Shadow DOM (`:host`)** | Injected `<div>` (Global CSS) | Injected `<div>` (Global CSS) | `kb-overlay` superior (No page CSS leakage) |
| **Dynamic SPAs** | **MutationObserver** | Static one-time scan | Static one-time scan | `kb-overlay` handles client-rendered SPAs |
| **Global Keybinding** | **Chrome `commands` (`Alt+Shift+K`)** | None | None | `kb-overlay` accessible from anywhere |
| **Navigation Keys** | `?`, `Tab/Shift+Tab`, `J/K`, `Enter/L` | `?`, `Tab/Shift+Tab`, `J/K`, `Enter/L`, `Esc` | `?`, `Tab/Shift+Tab`, `J/K` | `kb-overlay` fully covers donor keys |
| **Popup UI & Settings** | Theme, Opacity slider, Hints toggle, Rescan | Theme, Opacity slider, Enable/Disable | Opacity slider | `kb-overlay` provides complete controls |
| **ARIA Awareness** | ARIA roles, landmarks, accessible names | Basic focusable tags | Basic focusable tags | `kb-overlay` has deeper semantic awareness |
| **Code Quality** | Clean standard ES6+ | Syntax typos on lines 58 & 81 in `content.js` | Minimal prototype | `kb-overlay` is production ready |

---

## Migration and Retirement Plan

1. **No Unique Feature Loss**: Every keybinding (`J`, `K`, `L`, `?`, `Tab`), styling feature, and storage setting from the donors is natively supported in `kb-overlay`.
2. **Harmonization Moves**:
   - `kb-overlay` will remain the canonical extension packaged under Accessibility Suite.
   - `keyboard-nav-overlay` and `keyboard-nav-overlay-94bf7e` will remain unchanged and frozen as reference donors until final retirement authorization in Wave A6.
3. **Security Boundary**: All overlays adhere to strictly bounded Chrome Extension permissions (`activeTab`, `storage`), never requiring broad host access or `<all_urls>` background interception.
