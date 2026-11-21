# Instalación de la aplicación y audio del mando en macOS

## Paquetes finales de Karaoke 0.3.0

Cada Mac instaló su ZIP del commit `f73f563` y completó tres sesiones con el motor incluido. Pasaron las 21 comprobaciones de cada sesión, incluidos los dos cierres durante la reproducción y la recuperación de la cola al reabrir. Los tiempos corresponden a cada recorrido completo. Los tamaños y SHA-256 de los ZIP coinciden con los de los archivos subidos a GitHub.

| ZIP | Tamaño en bytes | SHA-256 | Tres sesiones | Evidencia |
|---|---:|---|---|---|
| `Karaoke-0.3.0-macos-arm64.zip` | 359.864.032 | `23a4a4c400a857cb8fd07a107b328d971f935d1efd80981c11ac6357bc44c912` | 53,38 s · 47,32 s · 47,00 s | [Apple Silicon](https://github.com/AlexAmMo/karaoke/actions/runs/44908926828/job/136860362379) |
| `Karaoke-0.3.0-macos-x86_64.zip` | 395.334.675 | `dcfe28936801138766a2a6af67a483e8a697a91f09888e296e483573e9bf6353` | 44,96 s · 41,98 s · 41,54 s | [Intel](https://github.com/AlexAmMo/karaoke/actions/runs/44908926828/job/136860362615) |

En ambas arquitecturas, la aplicación instalada descodificó la señal Opus de un teléfono simulado y admitió dos mandos con búsquedas independientes. La prueba del conversor PCM conservó las muestras mono en ambos canales y produjo 96.000 tramas al convertir dos segundos de 44,1 a 48 kHz. El recolector resolvió las 133 entradas de fuentes en Apple Silicon y las 138 en Intel.

## Pruebas previas de instalación y firma

El 21 de noviembre de 2026 se instaló el ZIP candidato en una carpeta temporal con `scripts/install.sh`. Se comprobó su SHA-256, la versión mínima declarada y el sello de la aplicación. Las sesiones utilizaron el motor y los recursos contenidos en el ZIP y una base de datos nueva. Las comprobaciones de canto usaron señal sintética y salida de audio de prueba.

| Paquete | Prueba del motor | Prueba de los mandos |
|---|---|---|
| Apple Silicon. ZIP local de 0.3.0, 311 Mach-O, macOS mínimo 26.0 | Las 21 comprobaciones de `scripts/test_session.py --check-panel` pasaron en 44,65 s. Se cantó, plegó el lateral y reinició conservando datos | Dos clientes buscaron, encolaron y controlaron reproducción. La app instalada negoció WebRTC y descodificó Opus |
| Intel x86_64. ZIP compilado por macos-15-intel, 368 Mach-O, macOS mínimo 15.0 | En el Mac Apple Silicon mediante Rosetta, las 21 comprobaciones pasaron en 80,56 s | Los dos mandos, la negociación y la primera trama Opus funcionaron. Se amplió el margen del primer enlace para la carga de códecs en frío |

La auditoría de ambos paquetes encontró cero referencias absolutas a bibliotecas externas. El ZIP Intel procedía de la compilación 479c72d. La verificación reveló que su `Engine.app` mantenía una firma que correspondía al plist anterior. Para esta prueba Intel se volvió a firmar el motor y después la aplicación exterior, se volvió a crear el ZIP y se instaló el resultado. En la rama de desarrollo el empaquetador ya realiza ambos sellados y sus verificaciones. La carpeta de prueba conservó la instalación habitual del usuario.

El empaquetado y la recogida de fuentes de ambas arquitecturas terminaron en los trabajos de [Apple Silicon](https://github.com/AlexAmMo/karaoke/actions/runs/44898191262/job/136828269960) e [Intel](https://github.com/AlexAmMo/karaoke/actions/runs/44898191262/job/136828270022). Las 18 descargas del [inventario de bibliotecas nativas de las ruedas](../../third_party/wheel-media-sources.json) se verificaron contra sus SHA-256, incluidas las cabeceras específicas de Windows. El [procedimiento reproducible](../PACKAGING.md) contiene los comandos para probar cualquier paquete posterior.

Los dos colectores comparten diez SHA-256 de Qt/PySide 6.11.3 comprobados con los ficheros Metalink que publica Qt. Al simular la caída del origen, el colector recuperó QtWebChannel del espejo de la Universidad de Erlangen-Núremberg y verificó su contenido. La regresión de red también cubre un espejo que devuelve bytes corruptos antes de que el siguiente complete la descarga. [Hashes de Qt](../../third_party/qt-source-checksums.json) · [Prueba del colector](../../tests/test_packaging_sources.py)

## Generación opcional

El generador final de Windows instaló un entorno Python 3.12 nuevo en 60,0 s. Con los modelos preparados tardó 66,3 s en procesar una mezcla de ocho segundos de «Mr. Fancy Pants». Produjo un mapa importable de 39 notas. Este ensayo comprueba instalación y ejecución. El [informe musical](generacion-iteracion.md) compara notas y sílabas frente a referencias independientes. [Trabajo de Windows](https://github.com/AlexAmMo/karaoke/actions/runs/44900914301/job/136836416498)

En macOS Intel se reprodujo un cierre al iniciar la separación vocal. PyTorch y CTranslate2 traían dos compilaciones de Intel OpenMP con la misma ABI. El proceso de generación ahora elige una sola biblioteca antes de cargar los modelos. En Apple Silicon bajo Rosetta se comprobó mediante la traza de dyld que todo el proceso de alta calidad usó una sola copia. El importador validó 39 notas con el perfil de calidad y 33 con el estándar para la misma mezcla de ocho segundos.

En macOS 15.7.9 sobre Intel, el entorno del generador de calidad se instaló en 20,3 s. Procesó los ocho segundos de la mezcla en 140,0 s y produjo un mapa de 39 notas. [Instalación y ejecución en macOS Intel](https://github.com/AlexAmMo/karaoke/actions/runs/44900914301/job/136836416684)
