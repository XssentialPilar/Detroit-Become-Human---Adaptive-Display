# Parche portátil de Detroit Adaptive Display 0.8.4

1. Cierra *Detroit: Become Human*.
2. Arrastra **DetroitAdaptiveDisplay-Patch.exe** desde el ZIP a la carpeta que contiene **DetroitBecomeHuman.exe**. En Steam puedes abrirla desde **Administrar → Ver archivos locales**.
3. Haz doble clic en **DetroitAdaptiveDisplay-Patch.exe** y espera el aviso con el resultado antes de abrir el juego.

El ejecutable comprueba la compatibilidad y aplica el parche automáticamente. Conserva la carpeta `DetroitAdaptiveDisplay.backup` para restaurar los archivos del juego.

## Restaurar

Cierra el juego y usa **Restaurar originales** en el instalador gráfico. También puedes abrir PowerShell en la carpeta del juego y ejecutar `.\DetroitAdaptiveDisplay-Patch.exe restore`. Ambos métodos utilizan la misma copia de seguridad.

Los comandos `verify`, `install` y `restore` siguen disponibles con las opciones `--game-dir` y `--lang`.
