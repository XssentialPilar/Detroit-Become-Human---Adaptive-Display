# Detroit Adaptive Display

Detroit Adaptive Display is a display patch for *Detroit: Become Human* on 64-bit Windows. It adjusts the camera, menus, and on-screen indicators for different aspect ratios. The full patch also crops prerecorded video proportionally and adds frame rate options of 30, 60, 90, 144, and Unlimited.

<img width="1920" height="1200" alt="Captura de pantalla 2026-11-17 205925" src="https://github.com/user-attachments/assets/5e2bad6d-7a7d-4182-a7de-9b9ad56d1bea" />


## Install the patch

Download one of the two ZIP files from **Releases** and close the game. [Release notes for v0.8.4](README-RELEASE.md)

- **Graphical installer.** Extract the EXE and DLL into the same folder. Open `DetroitAdaptiveDisplay-Setup.exe`, select the game folder, and click **Install patch**. The installer works offline and offers 25 languages. [Illustrated installation guide in Spanish](docs/INSTALACION.md)
- **Portable patcher.** Drag `DetroitAdaptiveDisplay-Patch.exe` into the folder containing `DetroitBecomeHuman.exe`, then double-click it. Wait for the result before starting the game. [Portable patcher guide in Spanish](docs/PARCHE_PORTATIL.md)

<img width="800" height="380" alt="02-compatible" src="https://github.com/user-attachments/assets/2d2cc1ab-ec89-4343-889c-37f49c22f3d9" />


The patcher saves the original files in `DetroitAdaptiveDisplay.backup` inside the game folder. Keep this folder while using the patch. With the game closed, select **Restore originals** in the graphical installer to undo the changes. Running the same patch again checks the existing installation and uses the same backup.

## Compatibility and testing

The full patch requires a supported game engine build and 11 compatible game resources. On other 64-bit builds, the interface mode can update supported menus and indicators. The installer checks your copy and shows which mode is available before applying any changes.

Automated layout tests cover 21 display sizes, including 4:3, 16:10, 5:4, 2.375:1, and 9:16. The Steam edition was used for in-game testing. The startup video and Connor’s on-screen indicator were checked visually at 1920 × 1200. Visual testing across all screens, aspect ratios, and window modes is still in progress. This release uses the game’s Vulkan renderer.

## Build from source

You’ll need 64-bit Windows, Python with Tk, and LLVM-MinGW. The build guide explains how to compile the executables, package the ZIP files, and run the tests. [Build and test guide in Spanish](docs/DESARROLLO.md)

| Path | What you’ll find |
| --- | --- |
| `installer.pyw`, `installer_gui.py`, `patch_cli.py`, `install.py` | Installer, portable patcher, and shared code for checking, applying, and restoring the patch. |
| `src/`, `include/`, `bin/` | Installer launcher, native patch code, and the verified patch DLL. |
| `tools/ui/`, `release.json` | Tools and checksums for patching resources from your own copy of the game. |
| `locales/`, `assets/`, `docs/` | Installer translations, icons, and guides. |
| `tests/`, `tools/` | Tests, diagnostics, and build and packaging tools. |

When reporting an issue, please include your game edition, display resolution, window mode, and the screen or scene where it occurs. A screenshot is helpful for visual issues.
