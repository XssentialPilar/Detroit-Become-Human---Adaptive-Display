# Compilación y pruebas

El usuario final puede abrir el EXE directamente. Para trabajar con el código fuente, usa Windows x64 y Python 3.10 o posterior con Tk. Ejecuta los comandos desde la raíz del repositorio.

## Interfaz e idiomas

El instalador usa una clave por mensaje en cada archivo de `locales/`. La elección se aplica a la ventana, al título del selector de carpetas, a los errores y al progreso. Los controles del selector nativo siguen el idioma de Windows. Los nombres de producto, de archivo y de carpeta conservan su escritura original. Puedes iniciar la interfaz en un idioma determinado con estos comandos.

```powershell
py -3 installer.pyw --lang es-419
py -3 installer.pyw --lang ar
```

Para comprobar el juego sin instalar el parche:

```powershell
py -3 install.py verify --game-dir "RUTA DEL JUEGO" --lang es-419
```

## Construcción

El generador de recursos forma parte del instalador. Lee los recursos originales y verifica que los resultados coincidan con las huellas publicadas en `release.json`. Para guardar una compilación local en `.work/`, apunta a una copia compatible con recursos originales:

```powershell
py -3 install.py prepare --game-dir "RUTA DEL JUEGO"
```

Estos comandos compilan el instalador gráfico y el parcheador de consola, y generan ambos ZIP en `dist/`.

```powershell
py -3 -m pip install -r requirements-dev.txt
py -3 tools/build_installer.py
py -3 tools/package_release.py
```

Para reconstruir la DLL se necesita un compilador `clang++` x64 de LLVM-MinGW. `py -3 build_native_loader.py` genera los reenvíos a partir de la copia de WinMM del sistema y escribe el resultado en `build/native/`. El instalador de esta versión utiliza el binario verificado en `bin/`. Un nuevo binario requiere actualizar las huellas y repetir las pruebas antes de distribuir otra versión.

## Pruebas

```powershell
py -3 tools/run_tests.py
cmake -S . -B build/policy
cmake --build build/policy --config Release
ctest --test-dir build/policy -C Release --output-on-failure
```

Para ejecutar también las pruebas de los recursos generados, completa antes el paso `prepare`. El visor de diagnóstico admite una ruta explícita al registro local:

```powershell
py -3 tools/diagnose_ui.py --once --anchors --trace "RUTA DEL JUEGO\DetroitAdaptiveDisplay.trace.csv"
```

## Distribución

El ZIP normal contiene el lanzador y una DLL privada de recursos. La DLL guarda el instalador interno y un ZIP con el código fuente, los catálogos, las guías y las huellas SHA-256. La herramienta de empaquetado usa LLVM-MinGW. Para recuperar el ZIP de fuentes, ejecuta este comando desde la carpeta del instalador.

```powershell
.\DetroitAdaptiveDisplay-Setup.exe --extract-source
```

El ZIP `-Portable` contiene el parcheador, su guía y las huellas SHA-256. La tabla de códigos de operación de AVM2 procede de Adobe avmplus e incluye el aviso y el texto de MPL 2.0 en `tools/ui/reference/`, que se incluye también en los ejecutables.

La comparación nativa usa todo el contenido de la imagen de referencia salvo tres campos de metadatos declarados en `release.json`. La tabla de certificados puede estar al final del archivo. El instalador y la biblioteca usan el mismo perfil. El modo de interfaz reconoce y verifica por separado el programa AVM2 de cada recurso, conservando el resto de su contenido. [Formato PE de Microsoft](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format)
