# Retorno de voz y reloj de puntuación

## Qué ocurría al cantar

El micrófono por cable en macOS ya podía devolver la voz directamente desde el callback dúplex de PortAudio. A continuación, ese mismo hilo esperaba un bloqueo para actualizar las muestras que usa el detector. El marcador tenía un problema independiente. Si la pantalla pasaba varios tiempos musicales sin actualizarse, Deluxe recuperaba los tiempos pendientes y los comparaba todos con la última ventana de voz disponible. Una nota cantada a tiempo podía recibir la altura de la siguiente.

El motor ahora guarda por cantante el audio reciente a 16 bits en memoria, con una marca temporal por bloque. El mezclador recibe la voz antes de la rama de análisis. Si el lector de muestras está ocupado, el callback sigue devolviendo la voz, cuenta el bloque de análisis que haya perdido y marca el corte. Una pausa de entrada, un desbordamiento indicado por el dispositivo o una pérdida de paquetes del móvil interrumpen la continuidad. El detector exige que la ventana de una nota esté completa dentro de un tramo continuo.

En PortAudio se traduce el reloj ADC del dispositivo al reloj monotónico del motor. Se alinea su origen con la entrega del primer bloque y se corrige la deriva lenta. En cada móvil se usa la cadencia de los paquetes de 20 ms y su número de secuencia. Así, una entrega puntual con retraso deja de mover la voz de una nota a otra; la compensación configurada mantiene su referencia y se aplica una vez. Los controladores SDL que únicamente entregan PCM se fechan al recibir su callback. Apple distingue expresamente el momento en que el sistema despierta ese hilo y la marca de la primera muestra capturada. [Relojes de CoreAudio](https://developer.apple.com/documentation/coreaudio/audiodeviceioproc?language=objc)

La puntuación utiliza la posición de reproducción del acompañamiento y el reloj monotónico del bloque, aplica el ajuste firmado de esa entrada y examina los 2.048 fotogramas centrados en el instante que corresponde a cada nota. A 48 kHz espera 21,3 ms tras ese instante para disponer de la segunda mitad de la ventana. Esa espera solo afecta al cálculo del punto. El trazo vocal sigue leyendo la muestra reciente y la ganancia sigue afectando únicamente a lo que se oye.

El recorrido de reserva, usado por las entradas móviles y el backend SDL distribuido en Windows, conserva como máximo un bloque de entrada más un periodo de salida, con un techo de 40 ms. Para una captura de 256 muestras y una salida de 512 a 48 kHz, el límite de voz pendiente en **esa cola** pasa de 40 a 16 ms. Para paquetes móviles de 960 muestras con la misma salida, el límite pasa a 30,7 ms. Son límites del mezclador. El controlador, la conversión de frecuencia, la red y el televisor tienen tiempos propios.

## Ajuste para cantar en casa

En **Sesión → Cantantes → Calibrar esta entrada**, «Escuchar mi voz» controla el retorno y «Compensación temporal» ajusta la puntuación en milisegundos. Si una entrada captura la voz 100 ms tarde, se puede guardar **+100 ms** para esa entrada. Si una interfaz de audio ofrece escucha directa, se puede usar el mando físico de la interfaz con el retorno de Karaoke a cero. El juego sigue capturando y puntuando el micrófono. [Escucha directa de una interfaz de audio](https://support.focusrite.com/hc/en-gb/articles/207546305-What-is-direct-monitoring)

La medición de siete pulsos desde la aplicación utiliza ahora la salida de la **música** incluso cuando el micrófono disfruta de retorno dúplex. De este modo el pulso y el acompañamiento pasan por el mismo mezclador. El resultado informa del recorrido salida acústica → entrada. La interfaz conserva el ajuste individual elegido por el anfitrión. La herramienta de diagnóstico permite medir aparte el recorrido dúplex del retorno.

## Qué hacen otros sistemas

- El equipo de PlayStation describe la puntuación por afinación en SingStar. Una patente de Sony, firmada por Richard Bates y Paulina Bozek, describe desplazamientos temporales para comparar segmentos vocales y su referencia. La documentación pública consultada no identifica los búferes internos, la latencia física ni el algoritmo exacto de retorno de la edición comercial de PS3. [Entrevista de PlayStation](https://blog.playstation.com/2007/07/04/inside-the-developers-studio-sarah-stocker/) · [Singing game processing, GB2403662A](https://patents.google.com/patent/GB2403662A/en)
- UltraStar Deluxe analiza el búfer del micrófono desde la detección de notas y desplaza el reloj mediante `MicDelay`. En el código de esa revisión el bucle de notas pendientes consulta de nuevo la captura actual. Esa es la base del caso de regresión. [Puntuación en UNote](https://github.com/UltraStar-Deluxe/USDX/blob/8b9d9e08eca997d2e3fe789084fbac136988f276/src/base/UNote.pas) · [Reloj de Deluxe](https://github.com/UltraStar-Deluxe/USDX/blob/8b9d9e08eca997d2e3fe789084fbac136988f276/src/base/UBeatTimer.pas)
- Performous ejecuta la puntuación en un hilo propio, en pasos de 10 ms, y consulta la posición de reproducción menos el ajuste de ida y vuelta. Su código actual también mezcla los micrófonos cuando se activa el retorno. La implementación confirma esta opción aunque una página antigua de su wiki todavía la describe como futura. [Reloj de Performous](https://github.com/performous/performous/blob/0e4c8c0c3b3c3e45a1bc552ab05d3c37fb60983f/game/engine.cc#L25-L44) · [Mezcla de micrófonos](https://github.com/performous/performous/blob/0e4c8c0c3b3c3e45a1bc552ab05d3c37fb60983f/game/audio.cc#L398-L414)
- Vocaluxe reproduce un tono de La a 440 Hz, consulta cuándo aparece en la entrada y mantiene un resultado por canal en su prueba de retardo. Nuestro banco de siete pulsos exige repeticiones coherentes antes de mostrar un valor. [Medición de Vocaluxe](https://github.com/Vocaluxe/Vocaluxe/blob/dfc721c9137cd0b3cbd4d69285e7930a2290f453/Vocaluxe/Lib/Sound/Record/CDelayTest.cs)
- PortAudio recomienda mantener las esperas fuera del callback. Distingue la latencia solicitada, la que admite el dispositivo y las marcas de tiempo de la primera muestra de entrada y de salida. Microsoft documenta que WASAPI puede negociar periodos pequeños mediante `IAudioClient3` cuando lo permiten el driver y el hardware. Esa posibilidad del sistema operativo no constituye una medición de nuestro paquete SDL. [Callback de PortAudio](https://portaudio.com/docs/v19-doxydocs/writing_a_callback.html) · [Latencia y relojes de PortAudio](https://github.com/PortAudio/portaudio/wiki/BufferingLatencyAndTimingImplementationGuidelines) · [Audio de baja latencia en Windows](https://learn.microsoft.com/en-us/windows-hardware/drivers/audio/low-latency-audio)

## Pruebas reproducibles

La regresión determinista genera 300 notas de 100 ms con dos alturas alternas, envía bloques de 5 ms y actualiza la puntuación cada 240 ms. Con el mismo PCM y el mismo observador de altura, usar siempre la última captura da **150/300**. Consultar la ventana de cada nota da **300/300**. El ensayo también cubre la reutilización del búfer circular, un bloque perdido, una desconexión y un cambio de ruta. Este ensayo comprueba el tiempo que se asocia a cada ventana. Las pruebas del motor completo utilizan el detector de Deluxe.

```sh
mkdir -p build/qa-audio
fpc -Funative -FUbuild/qa-audio -FEbuild/qa-audio scripts/test_audio_capture_history.pas
build/qa-audio/test_audio_capture_history
uv run python scripts/test_audio_score_clock.py --engine "$ENGINE"
uv run python scripts/test_group_audio.py --engine "$ENGINE"
uv run python scripts/test_trace_response.py --engine "$ENGINE" --output build/qa-audio/trazo.json
uv run python scripts/measure_monitor_clock.py --engine "$ENGINE" --input-name "Micrófono del MacBook Pro"
```

`ENGINE` es la ruta al ejecutable del motor recién empaquetado. Los tres ensayos de puntuación y dibujo utilizan PCM sintético con el renderizador real. El último comando abre el dispositivo físico con la escucha silenciada, sin grabar voz ni cambiar el volumen del sistema. Para un bucle acústico audible, con el equipo preparado, `scripts/measure_acoustic_route.py --music` mide el altavoz del acompañamiento y `scripts/measure_acoustic_route.py` mide la ruta de retorno; ambos aceptan `--engine` y `--input-name`.

## Mediciones en el MacBook Pro M4

Fecha de la prueba, 21 de noviembre de 2026. macOS 26.6.2, entrada y salida integradas a 48 kHz. Se mantuvo el volumen del sistema silenciado durante la prueba del controlador.

| Prueba | Versión instalada 0.3.0 | Motor con historial |
| --- | --- | --- |
| Seis cantantes simulados, precisión estricta, 10 fps, corrección individual de 0, +50, +100, +200, −50 y −100 ms | 9.479, 9.479, 9.271, 9.688, 9.792 y 9.479 puntos | 10.000 puntos en cada entrada |
| Séptimo cantante, misma carta y voz, +200 ms de retardo sin compensación | 2.813 puntos | 0 puntos |
| Tamaño real de captura del dispositivo, salida en modo dúplex | 64 muestras | 64 muestras |
| Tiempo ADC → DAC que comunica PortAudio, mediana / p95 | 9 / 9 ms | 9 / 9 ms |
| Errores de desbordamiento de entrada y agotamiento de salida en esas tomas | 0 / 0 | 0 / 0 |

Los ensayos de puntuación usan las mismas 48 notas alternas, el mismo sonido sintetizado y el mismo motor de afinación. El banco nuevo mantiene el reloj de la fuente sintética aunque la ventana dibuje tarde. La comparación determinista de 300 notas descrita arriba aísla la elección de la ventana sin variar el generador. El grupo de 1, 2, 3, 5, 6 y 10 cantantes verificó tanto la puntuación como el cese de puntos y la recuperación tras desconectar una entrada. A frecuencia normal, las seis compensaciones conocidas también alcanzaron 10.000 puntos y el control quedó en cero.

En otra repetición simultánea con inferencias pesadas en el Mac de 16 GB, el sistema llegó a tener 10 GiB de memoria cableada y solo 143 MiB sin usar. Se observaron paradas del proceso de entre 0,4 y 1,5 s durante el diagnóstico. Una pasada bajo esa carga dio entre 9.375 y 9.479 puntos en las entradas compensadas y cero en el control. Al repetir con el equipo descargado, las seis volvieron a 10.000. El motor deja sin punto una ventana de voz que no llegó completa.

En el ensayo de contención, dos cantantes enviaron PCM en paquetes de 20 ms al mismo receptor nativo. La prueba retuvo 180 ms el bloqueo del lector de análisis de uno de ellos. Durante ese intervalo se descartaron nueve bloques para calcular la nota de esa voz y cero para la otra. Al recuperar el lector, ambas entradas seguían teniendo retorno con picos de 4.000 unidades y entre 7 y 8 ms en cola en dos repeticiones. Ambas siguieron sumando puntos. En dos series de 33 cambios de tono entre Do2 y Sol5, la primera indicación visual correcta apareció en 18 ms de mediana. El p95 fue de 35,4 y 50,8 ms, con máximos de 37 y 52 ms respectivamente. La segunda indicación consecutiva llegó en 70 y 84,4 ms en p95. El tiempo empieza en la activación de la voz sintética y termina en el renderizador.

El recorrido completo de la app superó 21 comprobaciones, incluidas la pausa y reanudación, el panel plegable durante el canto, el cierre, la reapertura y la recuperación de la cola en orden.

La lectura nativa del dispositivo duró ocho segundos por versión y muestreó el informe del motor unas cinco veces por segundo. En la candidata se observaron 4 ms de mediana del ADC al callback y 5 ms de ahí al DAC. En una toma bajo carga se alcanzaron 22 ms de extremo a extremo según el controlador. No hubo desbordamientos indicados. La marca del controlador no incluye todos los efectos físicos del altavoz y el micrófono. Se hizo además una prueba acústica en esta sesión. Los altavoces integrados estaban al 35 % y la entrada al 27 %. Se emitieron siete pulsos por ruta con idéntica configuración para las dos versiones. En las tres tomas se reconocieron los siete, con una dispersión de 0 ms a la resolución de 1 ms del ensayo.

| Recorrido físico en el Mac | Latencia mediana |
|---|---:|
| Salida dúplex → altavoz → micrófono integrado en 0.3.0 | 73 ms |
| Salida dúplex → altavoz → micrófono integrado en 0.3.1 | 73 ms |
| Salida del acompañamiento por el mezclador → altavoz → micrófono en 0.3.1 | 104 ms |

El resultado acústico es compatible con la medición anterior de 72 ms en dúplex al 44 % de volumen. La comparación directa entre versiones muestra que el retorno físico dúplex de este Mac mantiene su latencia. La nueva calibración mide el acompañamiento por su propia ruta. El adelanto o retraso configurado para puntuar tampoco elimina un eco audible. Queda pendiente una medición con el micrófono por cable del usuario y con hardware Windows. [Lecturas de las tres pruebas acústicas](retorno-acustico-031.json) · [Medición anterior](audio-iteracion.md)

## Qué parte del retardo ve CoreAudio

Con los altavoces silenciados y ambos dispositivos inactivos se consultaron las propiedades HAL mediante `AudioObjectGetPropertyData`. A 48 kHz, macOS identificó dos dispositivos distintos en el mismo dominio de reloj. El búfer HAL en reposo era de 512 muestras para ambos; el bloque de captura observado durante el dúplex era de 64.

| Propiedad HAL | Micrófono integrado | Altavoces integrados |
|---|---:|---:|
| Latencia del dispositivo | 14 muestras · 0,29 ms | 60 muestras · 1,25 ms |
| Latencia adicional del flujo de audio | 1.439 muestras · 29,98 ms | 690 muestras · 14,38 ms |
| Margen de seguridad de E/S | 36 muestras · 0,75 ms | 48 muestras · 1,00 ms |

Apple especifica que las latencias de dispositivo y flujo se suman. Las dos latencias de flujo aportan **44,35 ms** declarados por el sistema. La biblioteca que distribuye Karaoke se identifica como PortAudio 19.7.0, revisión `147dd722`. Su cálculo de las marcas ADC/DAC usa el periodo, el margen de seguridad y la latencia de dispositivo. Omite la latencia del flujo y, cuando los dispositivos son distintos, también la cola que transporta las muestras de entrada al callback de salida. [Propiedad de latencia del flujo de Apple](https://developer.apple.com/documentation/coreaudio/audiohardwarestream/latency) · [Cálculo de las marcas de tiempo](https://github.com/PortAudio/portaudio/blob/147dd722548358763a8b649b3e4b41dfffbcfbb6/src/hostapi/coreaudio/pa_mac_core.c#L995-L1037) · [Ruta entre dos dispositivos](https://github.com/PortAudio/portaudio/blob/147dd722548358763a8b649b3e4b41dfffbcfbb6/src/hostapi/coreaudio/pa_mac_core.c#L2249-L2265)

**Estimación para este Mac.** Aplicando las propiedades anteriores al algoritmo de PortAudio y al perfil de baja latencia de Karaoke se obtiene una cola de 4.096 muestras con una precarga inicial de 1.024, equivalentes a **21,33 ms**. Junto con los 44,35 ms de los flujos, estas dos contribuciones rondan los 65,7 ms. La diferencia observada entre el pulso acústico y las marcas del driver fue de 64 ms. La proximidad explica el orden de magnitud. La ocupación real de la cola durante cada pulso y el reparto de los 31 ms adicionales del mezclador quedan sin medir. [Latencia predeterminada](https://github.com/PortAudio/portaudio/blob/147dd722548358763a8b649b3e4b41dfffbcfbb6/src/hostapi/coreaudio/pa_mac_core.c#L548-L568) · [Tamaño de la cola](https://github.com/PortAudio/portaudio/blob/147dd722548358763a8b649b3e4b41dfffbcfbb6/src/hostapi/coreaudio/pa_mac_core_utilities.c#L355-L408) · [Precarga inicial](https://github.com/PortAudio/portaudio/blob/147dd722548358763a8b649b3e4b41dfffbcfbb6/src/hostapi/coreaudio/pa_mac_core.c#L1939-L1984)

Con bloques explícitos de 64 muestras y una latencia solicitada de 10 ms para entrada y salida, ese algoritmo prevé una precarga de 256 muestras, unos 5,33 ms. La diferencia teórica respecto al perfil original es de 16 ms.

## Comparación acústica de los dos perfiles

En el mismo portátil se alternaron las dos configuraciones en el orden A/B/B/A. Cada toma abrió el motor desde cero y midió siete pulsos físicos del altavoz al micrófono a 48 kHz, con la salida al 35 % y la entrada al 27 %. La prueba utilizó un binario instrumentado que confirmó el perfil abierto. Las cuatro tomas ocuparon 27,43 s. Al concluir, el sistema recuperó el volumen de salida anterior y quedó silenciado.

| Orden | Perfil dúplex | Pulsos detectados | Mediana acústica | Dispersión del detector |
|---|---|---:|---:|---:|
| A | Original | 7/7 | 73 ms | 1 ms |
| B | 10 ms por sentido, 64 muestras | 7/7 | 57 ms | 0 ms |
| B | 10 ms por sentido, 64 muestras | 7/7 | 57 ms | 0 ms |
| A | Original | 7/7 | 73 ms | 0 ms |

El ahorro medido fue de **16 ms (22 %)**. Ambos perfiles siguieron mostrando 9 ms en las marcas ADC/DAC del callback. El descriptor de PortAudio estimaba 117,69 y 53,69 ms de entrada, respectivamente. La reducción de 64 ms en ese descriptor expresa un cambio de capacidad de búfer. El ensayo acústico midió el efecto real sobre el recorrido.

Con salida silenciada se procesó la entrada y su ganancia durante 45 s por perfil, con ocho procesos de cálculo en los diez núcleos lógicos del Mac. Se observaron 33.566 callbacks con el original y 33.607 con el perfil corto. Los cuatro contadores de desbordamiento y agotamiento de entrada y salida fueron cero en ambos. En otras dos sesiones se inyectaron fallos de apertura y de arranque del perfil corto por separado. El motor volvió a abrir la ruta dúplex original y continuó capturando en los dos casos. [Datos del ensayo](retorno-duplex-64.json)

El motor selecciona el perfil corto con CoreAudio en **Mac16,1**, entrada y salida integradas predeterminadas, a 48 kHz y con la latencia del dispositivo en automático. Para comparar se puede arrancar con `KARAOKE_DUPLEX_PROFILE=published`. El motor de distribución se probó silenciado en ambas configuraciones y confirmó el perfil efectivo con cero incidencias. En otros equipos, con micrófonos USB, con auriculares o con una latencia explícita se conservan los parámetros previos. Una regresión valida estos límites.

Los **57 ms** describen el recorrido físico de monitorización de esta pareja integrada. Los **104 ms** del acompañamiento se midieron en la configuración original. Su valor en el nuevo perfil queda pendiente. La compensación guardada para puntuar sigue siendo explícita. Quien ya la hubiera ajustado para esta pareja puede volver a medir en **Sesión → Cantantes → Calibrar esta entrada**. Las interfaces USB y Windows requieren sus propias mediciones.
