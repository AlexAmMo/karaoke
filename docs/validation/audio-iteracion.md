# Retorno, trazo y puntuación por entrada

Mediciones del 21 de noviembre de 2026 en un MacBook Pro M4 con macOS 26.6.2. El micrófono y los altavoces integrados estaban a 48 kHz. El volumen del sistema era del 44 % y la entrada, del 27 %. El anfitrión puede medir su propio equipo desde **Sesión → Cantantes → Calibrar esta entrada → Medir recorrido con pulsos**. La voz sigue puntuando con el retorno silenciado.

## Altavoz y micrófono reales

La app emitió siete pulsos de 32 ms a través de cada configuración de salida y buscó su envolvente a 1.700 Hz en el micrófono. La tabla recoge la mediana por configuración y la diferencia entre el mayor y el menor retardo observado. Se midió el tiempo desde entregar audio a la salida hasta recuperar la señal acústica en la entrada. Para atribuir el retraso únicamente al retorno de la voz hace falta medir su salida amplificada con una grabadora externa y una referencia independiente.

| Recorrido | Bloque de salida pedido a SDL | Mediana | Dispersión | Pulsos reconocidos |
| --- | ---: | ---: | ---: | ---: |
| Mezclador SDL | 2.048 | 144 ms | 1 ms | 7 de 7 |
| Mezclador SDL | 512 | 91 ms | 1 ms | 7 de 7 |
| Mezclador SDL | 256 | 96 ms | 5 ms | 7 de 7 |
| Mezclador SDL | 128 | 96 ms | 8 ms | 7 de 7 |
| PortAudio dúplex, voz directa desde el callback | Independiente del mezclador de música | **72 ms** | **0 ms** | **7 de 7** |

El tamaño más pequeño solicitado a SDL no produjo la menor latencia física. En este Mac el recorrido dúplex redujo en 19 ms la mediana frente a SDL con 512 muestras. El objetivo físico propuesto de 20 ms sigue pendiente. Faltan una interfaz USB con micro por cable, mediciones físicas en Windows y una prueba de 30 minutos con retorno real. La calibración conserva únicamente resúmenes de energía en memoria y rechaza una señal ambigua. Silencio y ruido sin pulsos se rechazaron a 44,1 y 48 kHz. La prueba determinista recuperó retardos conocidos de 0, 50, 100 y 200 ms en ambas frecuencias. En dos controles de la CLI, el motor capturó 214.144 y 213.632 muestras y emitió siete pulsos por intento. Reconoció cero y un pulso respectivamente y rechazó ambas estimaciones. Al consultar el estado del Mac al terminar, el sistema tenía la salida silenciada al 0 %. El tiempo acústico se muestra como diagnóstico. El ajuste manual de puntuación conserva su propio valor.

El motor intenta abrir la entrada y la salida a la vez con PortAudio en CoreAudio. El retorno usa la ganancia de cada voz y se suma en el mismo callback. Si el equipo rechaza el dúplex, prueba la entrada con retorno por el mezclador SDL. El modo estable se puede ensayar con `KARAOKE_MONITOR_PATH=mixer` y `KARAOKE_AUDIO_BLOCK=2048` al arrancar desde una terminal. Windows conserva su ruta SDL de captura y salida. El dispositivo de salida se identifica mediante el UID de CoreAudio o el endpoint WASAPI cuando el controlador lo permite. En otros controladores se consulta el nombre de la salida predeterminada informado por SDL. [Consulta de salida de SDL](https://wiki.libsdl.org/SDL2/SDL_GetDefaultAudioInfo) · [Tiempos de captura de PortAudio](https://files.portaudio.com/docs/v19-doxydocs/structPaStreamCallbackTimeInfo.html)

En una prueba adicional, los altavoces del Mac reprodujeron cuatro segundos de La4 sintetizado mientras la entrada real permanecía activa y el retorno silenciado. Al volumen descrito, el pico captado fue **0,93 % de escala**, las quince lecturas fueron de silencio puntuable y el marcador quedó en **0**. PortAudio informó de 4 ms entre la primera muestra de entrada y el callback y de 5 ms entre el callback y la salida DAC. Son cifras del controlador y no sustituyen el resultado acústico de 72 ms. Otros micrófonos, la distancia al altavoz, el volumen o una grabación vocal cambian la filtración y requieren su propia prueba.

## De la entrada al trazo

El banco inyectó PCM a 48 kHz en el motor y midió dentro del renderizador cuándo apareció la clase de nota correcta. Hizo tres recorridos de once tonos desde Do2 hasta Sol5. La segunda detección consecutiva confirmó la primera. Con el controlador SDL de prueba, en 33 transiciones el primer trazo acertado tardó **18 ms de mediana, 36,4 ms en p95 y 53 ms en el peor caso**. La confirmación de dos dibujos tardó 90,2 ms en p95. Estos tiempos empiezan al activar la entrada de prueba en el motor y terminan al preparar el trazo. La captura física, la red de un teléfono y el refresco de un televisor suman sus propios retardos.

Al probar el registro grave, la comparación circular anterior clasificó un Mi2 sostenido como Do. Ahora el detector compara únicamente muestras superpuestas y normaliza la diferencia para los 49 tonos. El análisis de la ventana reciente de 2.048 muestras se ejecuta fuera del bloqueo de captura. Con un solo cantante y con dos, la comparación de fotogramas verificó el trazo al desafinar hacia arriba y hacia abajo, silencio, nota acertada y voz sostenida durante un descanso.

## Compensación y multijugador

Dos fuentes independientes pueden tener distinto retraso. El ajuste temporal de cada una se aplica antes de redondear el tiempo al pulso de partitura. El control de precisión se refiere a la desviación en semitonos y sigue siendo independiente del volumen de retorno. En una ronda de siete voces sobre una secuencia de La4 y Do5, con compensaciones de 0, +50, +100, +200, −50 y −100 ms, las puntuaciones fueron **9.896, 9.896, 10.000, 10.000, 9.792 y 9.792** sobre 10.000. La séptima voz recibió la misma señal con +200 ms y sin corrección, y obtuvo 208. La diferencia máxima frente a la referencia compensada fue de 104 puntos. Una repetición después de corregir la detección en el registro grave obtuvo 10.000 en las seis voces corregidas y 0 en el control desfasado. Al introducir el receptor de audio independiente se repitieron los seis 10.000 y el control desfasado obtuvo 208.

Se ejecutaron actuaciones de **1, 2, 3, 5, 6 y 10 cantantes** con la ventana nativa real. La mitad de las entradas simulaban micrófonos físicos y las demás enviaban PCM por el transporte privado del host. En la ronda de diez, una voz desafinada obtuvo cero mientras las otras nueve puntuaban. También se comprobaron una desconexión y reconexión durante la nota, paquetes repetidos y de una actuación anterior, una ruta física duplicada y la liberación de reservas al terminar. Este banco comprueba diez voces digitales independientes. Diez teléfonos, diez conversores reales y las condiciones de una fiesta requieren pruebas físicas adicionales.

![Diez cantantes durante una actuación con el panel de sesión abierto](diez-voces.jpg)

## Recepción continua de móviles

Un primer ensayo de 20 minutos procesó cinco emisores de paquetes de voz y cinco entradas sintéticas locales, con cambios de panel y búsquedas periódicas. La versión que leía el socket desde el dibujo dejó **249–250 huecos de secuencia en unos 60.000 paquetes por emisor** bajo carga. Un segundo ensayo de 90 segundos con la salida real de CoreAudio observó 34 huecos por emisor sin interrupciones. Las muestras del mando ahora se reciben en un hilo dedicado que verifica la actuación, el cantante y la secuencia, y se une al cerrar antes de liberar la entrada. La puntuación sigue en el hilo del juego y la ganancia de retorno usa el mezclador de voz. Al repetir 90 segundos con los mismos diez canales y CoreAudio, se enviaron 22.525 datagramas. El motor contabilizó los 22.525, rechazó los 154 paquetes de prueba con secuencia o turno inválido y registró cero huecos en los flujos ininterrumpidos. La voz desconectada dejó de puntuar mientras las demás continuaron.

En la repetición de **20 minutos reales** del motor `508c360`, anterior al cambio de conversor SDL, se enviaron 300.020 datagramas y el motor contabilizó todos: 297.415 válidos y 2.605 repeticiones o paquetes con identificador inválido durante 17 cortes forzados. Las cuatro entradas móviles sin cortes recibieron sus 60.004 paquetes cada una, sin huecos. La voz con cortes consiguió 7.660 puntos, las ocho voces afinadas estables entre 7.985 y 7.987 y la voz desafinada obtuvo cero. El panel siguió respondiendo, con un intervalo p95 de 220 ms entre estados distintos. La canción avanzó 1.115,2 s en 1.200,08 s de reloj real con SDL dummy. En las dos voces con retorno activado, las colas alcanzaron su límite de 40 ms y descartaron 3.829.440 y 4.022.608 muestras respectivamente para mantener reciente la voz. Es una pérdida del retorno por el ritmo distinto del dispositivo de prueba. La captura de puntuación conservó las secuencias de entrada y se midió por separado.

En una prueba adicional de 90 s con la salida CoreAudio real, dos voces enviaron señal al mezclador con una ganancia de 0,01. El sistema operativo permaneció silenciado. El motor contabilizó los 22.500 datagramas; los 151 inválidos fueron los inyectados al simular el corte. La cola de retorno llegó a 35 ms para la voz móvil y 40 ms para la entrada sintética local. Se descartaron 1.280 y 8.480 muestras respectivamente, equivalentes a 26,7 y 176,7 ms acumulados durante toda la prueba. La medición comprueba los contadores del mezclador. Para valorar si se oye algún corte hace falta una escucha con la salida activada. [Contadores de las tres ejecuciones](audio-pruebas-sostenidas.json)

## Cierre durante el canto

El paquete anterior registró un aborto intermitente en `swr_convert` en el runner macOS arm64. LLDB localizó el fallo en el convertidor de salida del mezclador en el hilo de audio SDL. En una reproducción el hilo principal estaba dibujando el panel. La revisión `3f39086` espera a que terminen los callbacks antes de liberar las pistas, los efectos y la captura. Cada pista también espera al mezclador al retirarse, incluso cuando el lector ya marcó su final y sigue tratando el último bloque. En el Mac M4 local pasó el recorrido completo de restauración. Otros **20 cierres durante los primeros segundos de Probe C** acabaron con cero: diez con entradas locales sintéticas y diez con un receptor PCM móvil activo. El binario anterior también pasó 20 intentos locales; el runner donde sí ocurrió el fallo aporta la comparación independiente. [Pila de LLDB del paquete original](https://github.com/AlexAmMo/karaoke/actions/runs/44905675925)

## Conversión de la salida y del retorno

La traza adicional del ejecutable anterior identificó la pista musical decodificada, a 48 kHz y con un canal, al convertirla a estéreo. En el ensayo instrumentado el decodificador produjo 4.096 tramas y la capacidad del destino era de 4.096 tramas. La versión `bb2145f` conserva FFmpeg para decodificar los ficheros y usa un `SDL_AudioStream` persistente por pista o voz para la conversión de salida. El mezclador consulta los bytes disponibles, conserva la fase al recibir bloques sucesivos, drena el último bloque de la canción y vacía el estado al buscar. [API SDL de conversión continua](https://wiki.libsdl.org/SDL2/SDL_NewAudioStream)

En el Mac con SDL2-compat, los 65.536 posibles valores de una muestra PCM de 16 bits se copiaron exactamente a ambos canales. Las muestras estéreo permanecieron idénticas. Dos segundos de La4 a 44,1 kHz produjeron 96.000 tramas a 48 kHz y 880 ciclos. El fichero entero y los seis tamaños de bloque alternos generaron la misma salida muestra por muestra. En el binario nativo pasaron el cambio de canción, la restauración de cola y el cierre, y el primer trazo de las 33 transiciones tardó 37 ms en p95. Seis voces compensadas consiguieron 10.000 puntos y el control con 200 ms de desfase obtuvo cero.

Para elegir el runtime de Windows se probó también el código fuente de SDL 2.32.10 con el mismo banco. El valor −32.768 se convirtió en −32.767 y la prueba fraccionada produjo 95.422 tramas, 578 menos de las esperadas. La revisión `51d46e7` empaqueta SDL2-compat con SDL3 en Windows y registra las huellas y las fuentes de ambas. El banco se ejecuta en CI con las DLL que acompañan al juego. [Distribución SDL2-compat de MSYS2](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-sdl2-compat)

Se repitió el ensayo de diez voces con el mezclador SDL de `bb2145f`. En **1.200,005 s** llegaron 300.000 datagramas: 297.386 válidos y 2.614 inválidos generados por los 17 cortes controlados. Cada voz móvil estable recibió sus 60.000 paquetes. Las ocho voces estables afinadas obtuvieron 7.835 puntos, la voz interrumpida 7.511 y la desafinada cero. Con salida SDL dummy la canción avanzó 1.093,51 s de su reloj. Las dos colas de retorno se mantuvieron dentro de 40 ms y descartaron 4.784.640 y 5.017.104 muestras para seguir el reloj más lento de ese dispositivo virtual. Con el reloj real CoreAudio se ejecutó además un ensayo de 90,098 s, con 22.525 datagramas, un corte, 155 rechazos esperados y ningún descarte contabilizado en el retorno. El sistema estaba silenciado en este último ensayo. Se comprobó el procesamiento de señal, no su percepción acústica. [Resultados del mezclador SDL](audio-sdl-mediciones.json)

## Paquete de Windows

El candidato `abdc378` arrancó en Windows Server 2022 desde la aplicación congelada x64. El recorrido offline buscó una canción ya descargada, la añadió, abrió la cola y empezó a cantar. Plegar y desplegar el panel mantuvo el cursor visible. En una copia desechable del mismo ejecutable con Mesa por software y audio SDL dummy pasaron el trazo, las tres precisiones con dos voces, la compensación por entrada, actuaciones desde una hasta diez voces y la gestión remota de la cola. Las 33 transiciones desde Do2 hasta Sol5 dieron **20 ms de mediana** para la primera nota correcta, **42,4 ms en p95** y **43 ms de máximo**. La segunda confirmación tardó 80,4 ms en p95. El SHA-256 del ZIP que utilizó el banco fue `fc588776c7368973679bc454043e432e5ff45122334b5350bdd3ddef061faada`. El runner emplea gráficos y audio virtuales; la latencia física de Windows sigue pendiente. [Pruebas del paquete de Windows](https://github.com/AlexAmMo/karaoke/actions/runs/44902923405/job/136842501548)

## Reproducción

Desde la raíz del repositorio con el motor compilado, `RUTA_MOTOR` representa el ejecutable de Deluxe modificado. Cada ejecución usa datos temporales. Las pruebas de PCM sintético usan SDL dummy y pueden abrir una ventana real.

```sh
mkdir -p build/audio-qa
fpc -Fu./native -FUbuild/audio-qa -FEbuild/audio-qa scripts/test_audio_calibration.pas
build/audio-qa/test_audio_calibration
uv run python scripts/test_trace_response.py --engine RUTA_MOTOR --output build/audio-qa/tiempos.json
uv run python scripts/test_group_audio.py --engine RUTA_MOTOR --output build/audio-qa
uv run python scripts/test_pitch_precision.py --engine RUTA_MOTOR
uv run python scripts/test_live_pitch.py --engine RUTA_MOTOR --output build/audio-qa/afinacion
uv run python scripts/soak_group_audio.py --engine RUTA_MOTOR --seconds 1200 --output build/audio-qa/sostenida.json
uv run python scripts/soak_group_audio.py --engine RUTA_MOTOR --seconds 90 --system-playback --monitor-gain 0.01 --output build/audio-qa/mezclador.json
```

Para repetir la prueba física, usa el nombre exacto de la entrada que aparece en el sistema. Este comando abre la aplicación con un perfil temporal y emite siete pulsos breves. Funciona también con un ejecutable empaquetado pasando `--launcher` en lugar de `--engine`.

```sh
uv run python scripts/measure_acoustic_route.py --engine RUTA_MOTOR --input-name "Micrófono del MacBook Pro" --output build/audio-qa/recorrido.json
```
