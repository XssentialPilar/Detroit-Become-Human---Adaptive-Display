# Detroit Adaptive Display v0.8.4

This release includes a graphical installer and a portable patcher for *Detroit: Become Human* on 64-bit Windows. Both apply the same patch and create a backup of the original game files.

## Downloads

| Download | What’s inside |
| --- | --- |
| `DetroitAdaptiveDisplay-0.8.4.zip` | The graphical installer and one companion DLL. The DLL contains the installer’s resources, source code, and guides. |
| `DetroitAdaptiveDisplay-0.8.4-Portable.zip` | A portable patcher you can run with a double-click, a short guide, and file checksums. |

To verify your download, compare the ZIP’s SHA-256 checksum with the value in the matching `.sha256` file attached to this release.

## Installation

Close the game, then choose either method below. To find the game folder in Steam, right-click the game in your Library and select **Manage → Browse local files**.

**Graphical installer**

1. Extract the EXE and DLL into the same folder.
2. Open `DetroitAdaptiveDisplay-Setup.exe`.
3. Select the game folder and click **Install patch**. If you select a subfolder such as `ShaderCache`, the installer finds the main game folder.

**Portable patcher**

1. Drag `DetroitAdaptiveDisplay-Patch.exe` into the folder containing `DetroitBecomeHuman.exe`.
2. Double-click the patcher and wait for the result before starting the game.

## Restore the original files

Keep `DetroitAdaptiveDisplay.backup` in the game folder while using the patch. To undo the changes, close the game and select **Restore originals** in the graphical installer. You can also open PowerShell in the game folder and run `.\DetroitAdaptiveDisplay-Patch.exe restore`.

If you run **Install patch** again on a recognized installation, the patcher checks the existing files and reuses the backup.

## Compatibility and testing

The full patch adjusts the camera, prerecorded video, menus, on-screen indicators, and frame rate options. On other 64-bit game builds, interface mode can update compatible menus and indicators. The installer shows which mode is available before applying the patch.

Installation, repeat installation, and restoration were tested using isolated copies. Steam was the commercial edition available for in-game testing. Interface mode was also tested on a simulated alternative build. Visual testing across all screens and aspect ratios is still in progress.

## Source code

The graphical installer includes the source code and guides in its companion DLL. To extract `DetroitAdaptiveDisplay-0.8.4-Source.zip`, open PowerShell in the folder containing both installer files and run the following command.

```powershell
.\DetroitAdaptiveDisplay-Setup.exe --extract-source
```
