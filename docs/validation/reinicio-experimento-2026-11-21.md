# Reinicio durante el ensayo de separación vocal

El 21 de noviembre el Mac se reinició por un bloqueo del sistema durante la investigación posterior a 0.3.1. El ensayo afectado es el separador experimental BS Roformer de voz principal; no forma parte del instalador público de Karaoke. La generación casi perfecta sigue sin estar demostrada y esta incidencia impide promover ese separador.

## Evidencia conservada

El informe de macOS `panic-full-2026-11-21-195714.0002.panic` registra un **watchdog sin respuesta durante 90 segundos**. Su reloj interno (`Calendar: 0x6b01e948`) sitúa el fallo a las 19:56:08 de Madrid; el Mac arrancó a las 19:56:33 y escribió el informe a las 19:57:14. El proceso que entra en pánico es `kernel_task`, por lo que el informe no es una excepción Python que identifique por sí sola una línea del adaptador.

En la captura del fallo había **15,34 GiB de memoria inmovilizada** de los 16 GiB del Mac y aproximadamente 14 MiB libres. Un proceso Python figuraba con 10,70 GiB residentes. Había otras cargas, incluida una máquina virtual con 8,02 GiB residentes; estas cifras de procesos pueden compartir páginas y no deben sumarse como memoria física independiente. La zona del núcleo `kalloc.1024` ocupaba unos 6 GB. El resumen local conserva sólo los campos relevantes y la huella del informe original: `build/generation-next/reboot-2026-11-21/summary.json`.

El control previo del separador procesaba **dos segundos** sintéticos en CPU y MPS. Comprobó forma de salida y diferencias numéricas pequeñas entre ambos, pero no estableció que la configuración de **veinte segundos** fuese adecuada para la memoria disponible. El directorio del primer piloto completo se creó antes del fallo; no llegó a conservar una canción separada completa.

## Causa probable y límite de la conclusión

El modelo utiliza atención sobre el tiempo. Con 62 bandas, ocho cabezas y unos 1.723 fotogramas, una única matriz densa de atención en float32 requiere aproximadamente **5,9 GB**. Con dos segundos es unas cien veces menor. La implementación publica optimizaciones específicas para CUDA; la ruta MPS no garantiza el mismo consumo. La operación de atención incluye una matriz entre posiciones temporales y una normalización posterior. [Definición de atención en PyTorch 2.8](https://docs.pytorch.org/docs/2.8/generated/torch.nn.functional.scaled_dot_product_attention.html)

El crecimiento de asignaciones del ensayo MPS, combinado con la carga del sistema, es la explicación más probable. La coincidencia temporal, el tamaño previsto y la captura de memoria la respaldan. **No demuestran que sea la causa exclusiva ni identifican un defecto concreto del controlador de Apple.** No se vuelve a provocar un pánico para intentar obtener una confirmación más fuerte: la investigación utiliza el informe capturado y comprobaciones que rechazan la configuración antes de cargar el modelo.

Al retomar la sesión se relanzó el ensayo antes de conocer el aviso del reinicio. Se detuvo en cuanto el usuario lo comunicó. El proceso no respondió inmediatamente a las señales de cierre y quedó en estado de salida con RSS cero; la memoria inmovilizada descendió después de unos 12,4 a 3,1 GiB. Finalmente se confirmó la salida del proceso y su supervisor, con código 143. El registro de ese segundo intento mide 227,48 segundos, RSS máximo de 942.161.920 bytes y **huella máxima de memoria de 15.516.288.440 bytes (14,45 GiB)**. Son medidas distintas: el RSS aislado no reflejaba toda la huella de memoria. Esta medición refuerza la decisión de retirar la ruta MPS, aunque no identifica de forma definitiva el motivo del primer fallo del núcleo.

## Continuación acotada

Se bloquea MPS en el adaptador experimental antes de importar PyTorch o cargar pesos. La ruta de continuación pasa a CPU, ventanas de cuatro segundos, estimación conservadora de memoria y límite de tiempo por canción en un subproceso. Si una configuración supera el presupuesto o un trabajador no termina, no se lanza otra canción. Los planes y resultados anteriores se conservan; la configuración nueva exige otro directorio y otro manifiesto.

Las diez pruebas de regresión comprueban el rechazo de MPS y de la ventana de veinte segundos antes de cargar modelos, la conservación del plan anterior, la escritura completa de resultados y la terminación de un subproceso ordinario al agotar su plazo. También comprueban el cierre del trabajador cuando se interrumpe su supervisor y que el control sintético utiliza el mismo supervisor. Pasaron en 0,27 segundos y una segunda revisión independiente las volvió a ejecutar. No cargan modelos ni reproducen el fallo del sistema.

La suite completa, que incluye estas [pruebas de límites](../../tests/test_lead_vocals_limits.py), pasa **240 pruebas en 19,42 segundos** en el Mac después del reinicio. Se conserva el informe original de macOS y un resumen de campos relevantes; no se publica su volcado de procesos ni se modifica el sistema para reproducirlo.

El mismo código del commit `04f2945` pasa las 240 pruebas en los runners de macOS, Ubuntu y Windows Server 2022 de la [ejecución 44939711109](https://github.com/AlexAmMo/karaoke/actions/runs/44939711109). Esa ejecución valida las guardias y la suite Python; no ejecuta el separador, construye instaladores nuevos ni acredita estabilidad de hardware Windows.

La estimación previa es de 1,29 GiB para cuatro segundos y 17,09 GiB para veinte; el umbral es 2 GiB. Es una estimación preventiva, **no un límite garantizado de memoria del proceso**.

Después de comprobar la recuperación de memoria se ejecutó un único control sintético de **cuatro segundos en CPU**, con plazo máximo de 60 segundos, en otro directorio (`pilot-cpu-v2-probe-60s`). Terminó con salida cero, 2,91 segundos de inferencia y 5,04 segundos totales. La salida conserva las 176.400 muestras de los dos canales y todos sus valores son finitos. El pico RSS observado por `time -l` fue 1.057.406.976 bytes (1.008,42 MiB). Su campo de huella física corresponde al supervisor externo, no al trabajador que cargó el modelo: no se compara con la huella de 14,45 GiB del ensayo MPS como si fueran mediciones equivalentes. La memoria inmovilizada del sistema se mantuvo en unos 1,51 GiB y el trabajador terminó y fue recogido.

Este primer control comprueba una inferencia corta con la ventana nueva; no validaba por sí solo una canción completa, el solapamiento de ventanas o la calidad musical. La continuación posterior se registra a continuación. El Mac permanece silenciado y no se modifica la instalación pública 0.3.1.

El selector de letras prosigue de forma independiente sobre probabilidades ya guardadas: no carga modelos ni utiliza GPU. Su cálculo CTC usa dos filas reutilizables en lugar de almacenar la retícula completa; el ensayo de cuarenta canciones terminó con unos 46 MiB de memoria residente. Esto permite continuar la investigación mientras se verifica la prevención del incidente.

Las guardias reducen el riesgo concreto de repetir la configuración observada. No equivalen a una garantía de que macOS no vuelva a bloquearse ni a una validación musical de la nueva ventana del separador.

## Supervisión del trabajador y canción completa posterior

La revisión `2ed7467` añade el muestreo nativo del **trabajador**, mediante `proc_pid_rusage`, cada 50 ms. Observa RSS y huella física; detiene el proceso si alcanza 1,5 GiB en cualquiera de las dos medidas, pierde la telemetría o agota el plazo, y espera a recogerlo antes de continuar. Cinco controles adicionales verifican ese comportamiento sin grandes asignaciones. La [ejecución 44940393293](https://github.com/AlexAmMo/karaoke/actions/runs/44940393293) pasa 245 pruebas en macOS y 244 más una omisión de la API Apple en cada runner de Linux y Windows. No ejecuta el separador en esos runners.

Con esta supervisión, el ensayo CPU v3 termina **Amorfoda completa**, 176,854807 segundos y 7.799.297 muestras, sin pérdida de longitud ni valores no finitos. Tarda 532,968 segundos en separar y 534,43 en total. Sus 10.285 observaciones registran como máximos 1.353.056.256 bytes RSS (1.290,38 MiB) y 1.267.009.264 bytes de huella física (1.208,31 MiB); el trabajador sale con código cero y queda recogido. El registro externo mide 16 KiB más de RSS que el muestreo: se mantiene explícita la limitación temporal de la vigilancia.

La salida queda fijada por SHA-256 `11ebd8980153f04e9795811081d1d547abbdf938286b1de86a67d1caa0dd97bd` en `build/generation-next/lead-vocals/pilot-cpu-v3/`. Es evidencia de ejecución acotada de una canción en este M4. La calidad musical y la comparación de notas son pruebas distintas, descritas en [el informe de voz principal](research-voz-principal-2026-11-21.md).

En la comparación posterior, GAME sobre la voz original alcanzó el límite de 1,5 GiB después de 21,4 segundos. La guardia lo detuvo con código −9 y confirmó su recogida; la segunda mitad del par no se lanzó. Se preservó `paired-cpu-v4` y se preparó otra política de retención de memoria para un directorio nuevo. Este corte preventivo no fue otro reinicio ni demuestra un fallo del sistema operativo.

La política sin arena de ONNX tampoco terminó bajo ese límite. Un único ensayo diagnóstico posterior conservó los mismos parámetros y registró las fases: las cinco sesiones se cargaron con unos 527 MB RSS; después de tres ventanas el proceso tenía unos 1.436 MB, y la cuarta activó el corte. Se confirmó nuevamente su cierre. Esto localiza crecimiento entre ventanas de GAME, distinto del episodio MPS; todavía no identifica qué asignaciones lo retienen. Los ensayos truncados y sus fuentes se conservan, sin mapas finales ni conclusiones de precisión.

La continuación por ventanas independientes sí terminó los dos brazos de Amorfoda: veinte trabajadores, todos con salida cero y cierre confirmado, con máximo observado de 1.025,72 MiB RSS. Cada trabajador procesa una ventana y termina, de modo que no conserva sus asignaciones para la siguiente. Reiniciar el generador aleatorio por ventana constituye una configuración nueva, declarada igual en ambas voces; no se afirma identidad numérica con los ensayos anteriores. La evaluación musical posterior sigue sin superar los cinco controles y no se ha incorporado este método a la app. Los [resultados pareados](research-voz-principal-2026-11-21.md) separan claramente ejecución acotada y calidad.

## Uso de la instalación pública después de recuperar el sistema

Se volvió a ejecutar `scripts/test_session.py --check-panel` mediante el lanzador del acceso del escritorio, con una carpeta temporal del sistema y audio sintético. La aplicación instalada 0.3.1 pasó las **21 comprobaciones en 33,96 segundos**: importar y encolar, dos cantantes con puntuación independiente, cambiar de canción, cerrar durante un turno, reabrir y recuperar la cola en su orden sin iniciar reproducción automáticamente. El cierre final terminó correctamente y la salida del Mac siguió silenciada.

Los hashes del lanzador y del motor coinciden con los de la [entrega pública](entrega-0.3.1.json): `0b7137d27b4438be221bcb34f52f6adab90ed0713daaec263761899a74036931` y `a1f9666ef7eb831c8ddb950c66e49c27931a9118f082cf7c34f2f328c20df28e`. No se reinstaló ni sustituyó la aplicación. La evidencia local está en `build/generation-next/reboot-2026-11-21/installed-session-after-recovery.json`, SHA-256 `9328a470abe9064944b9bc3c794bad937337589c988f715ed6d55131940ab6d5`.

Esta comprobación usa el M4 físico y el motor instalado, pero entrada de audio sintética. No vuelve a medir latencia acústica, micrófonos ni estabilidad de Windows; verifica que el recorrido cotidiano completado sigue funcionando después del incidente.
