# Entrega de Karaoke 0.3.1

La versión preliminar [v0.3.1](https://github.com/AlexAmMo/karaoke/releases/tag/v0.3.1) se publicó el 21 de noviembre de 2026 desde `cf33bf4734dc49f0487d5e52d77662b441b82589`. Se reutilizaron los paquetes de la [compilación 44924838402](https://github.com/AlexAmMo/karaoke/actions/runs/44924838402), aprobada en macOS Apple Silicon, macOS Intel y Windows. Las pruebas Python también pasaron en macOS, Windows y Linux.

## Paquetes publicados

La [verificación 44924880563](https://github.com/AlexAmMo/karaoke/actions/runs/44924880563) comprobó el commit de origen, los binarios ejercitados, las fuentes correspondientes y los SHA-256 antes de subir los archivos al borrador. Los 19 archivos publicados coinciden en nombre, tamaño y hash con los informes verificados. Se descargaron y cotejaron todos los archivos de sumas; la etiqueta pública resuelve al commit probado.

| Paquete | SHA-256 |
|---|---|
| macOS Apple Silicon | `f7878e4a228d0326a33b143ccd92b5968574093fa93b52f8caab86ec271d5147` |
| macOS Intel | `20ea3372af041c7df4521aee40768c9f3532a64c1b8bd127d56b473bf0db7272` |
| Windows x64 | `b47e9d51b2c1592e2563f63a7b678079c1d29fa39b9c4bf2d1858fc1053ad97a` |

## MacBook Pro M4 físico

En el Mac16,1 con macOS 26.6.2 se comprobó primero el ZIP candidato: firma de la aplicación y del motor, procedencia y 21 comprobaciones de sesión en 34,26 s. Tras publicar se ejecutó el comando público de instalación sobre la 0.3.0. El instalador terminó correctamente y los 204 archivos de la carpeta de datos conservaron sus hashes. Se guardó una copia local de recuperación. Después de abrir la aplicación, las cinco canciones y los seis ajustes conservaron también sus valores en SQLite.

El acceso `Karaoke.app` del escritorio apunta a `~/Applications/Karaoke.app`, cuyo lanzador devuelve `Karaoke 0.3.1` y coincide con el paquete público. La apertura mediante LaunchServices con datos temporales del sistema y audio sintético llegó al estado listo en 1,22 s. Se observó además la ventana de Karaoke con la biblioteca habitual y su turno pendiente. Ambas sesiones cerraron correctamente.

La app instalada superó las 21 comprobaciones de `scripts/test_session.py --check-panel` en 33,81 s: importar, encolar, cantar y puntuar con señales sintéticas, cambiar de canción, cerrar durante el canto, reabrir y recuperar la cola en orden. `scripts/smoke_desktop.py --check-cursor` verificó los controles Buscar → Añadir a la cola → Cola → Empezar a cantar y el cursor durante los cambios del panel. Cada recorrido usó datos de prueba aislados.

`scripts/experiments/recover_verified_turn.py` reutilizó la predicción original guardada de «Amorfoda». El paquete instalado la verificó contra la misma grabación, conservó el turno de Luna, admitió el mapa y llegó al canto. La predicción conserva el hash `5ed3a759a593f5ac9f85e872833482c7e1d75fd45be8b4568a26ef1ed2f2c504`.

Un primer ensayo con `--data-dir` dentro del proyecto en el Escritorio no llegó a crear IPC en 45 s. El proceso seguía vivo y se detuvo desde el ensayo. Las aperturas posteriores con la carpeta temporal del sistema y con la ubicación habitual funcionaron. La causa de ese intento queda sin determinar; no se amplió su investigación. No se observaron cierres inesperados en los recorridos completados.

El Mac permaneció silenciado. Se conservan las mediciones acústicas anteriores de 73, 57, 57 y 73 ms, con un ahorro de 16 ms en esta pareja de dispositivos integrados. Esta entrega no repitió la medición física. [Retorno y puntuación](retorno-y-puntuacion.md).

## Instalación pública en Windows virtualizado

Se ejecutó `verify-installation.yml` con `tag=v0.3.1` y referencia `v0.3.1`. La [ejecución 44928052615](https://github.com/AlexAmMo/karaoke/actions/runs/44928052615) terminó correctamente en una VM de Azure con Windows Server 2022 y PowerShell 5.1.20348.5773.

El comando público descargó sin credenciales el instalador y el paquete, verificó SHA-256, instaló la 0.3.1 y creó el acceso directo de Inicio con el destino y directorio de trabajo correctos. Un archivo previo en la carpeta de datos conservó su hash. La prueba de Windows usa ese archivo testigo; la conservación de una biblioteca poblada se comprobó en el Mac.

Una copia de la aplicación instalada, con Mesa llvmpipe y salida SDL dummy, superó las pruebas de dos cantantes sintéticos bajo las tres precisiones de afinación. Se comprobaron 12 combinaciones de precisión y desviación, 24 incrementos individuales de puntuación, pérdida de entrada y recuperación. Tres contextos Chrome con perfiles iPhone 13, Pixel 7 e iPhone SE verificaron buscar, encolar, editar turnos, reintentar sin duplicar, sincronizar la cola, reconectar y cerrar la sala.

Esta evidencia permite comprobar la instalación y el funcionamiento de software en Windows. Quedan pendientes el audio, la GPU y los micrófonos de un PC físico, así como teléfonos y Wi-Fi reales. Los runners macOS comprobaron también tres sesiones completas de 21 controles por arquitectura. La instalación local corresponde al Mac de desarrollo; no representa un Mac limpio.

## Instalación

macOS:

```sh
curl -fsSL https://raw.githubusercontent.com/AlexAmMo/karaoke/v0.3.1/scripts/install.sh | KARAOKE_VERSION=v0.3.1 bash
```

Windows PowerShell:

```powershell
$env:KARAOKE_VERSION='v0.3.1'; irm https://raw.githubusercontent.com/AlexAmMo/karaoke/v0.3.1/scripts/install.ps1 | iex
```

[Evidencia resumida de esta entrega](entrega-0.3.1.json). Los resultados de las 40 grabaciones permanecen en [el informe de generación](generacion-youtube-y-retorno.md): «Amorfoda» supera todos los controles; «Northern Star» sigue en revisión y las grabaciones sin referencia fiable permanecen como borradores.
