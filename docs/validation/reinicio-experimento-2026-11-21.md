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

Este control comprueba una inferencia corta con la ventana nueva; **no valida todavía una canción completa, el solapamiento de ventanas o la calidad musical**. No se continuó automáticamente con el piloto musical. El Mac queda silenciado y no se modifica la instalación pública 0.3.1.

El selector de letras prosigue de forma independiente sobre probabilidades ya guardadas: no carga modelos ni utiliza GPU. Su cálculo CTC usa dos filas reutilizables en lugar de almacenar la retícula completa; el ensayo de cuarenta canciones terminó con unos 46 MiB de memoria residente. Esto permite continuar la investigación mientras se verifica la prevención del incidente.

Las guardias reducen el riesgo concreto de repetir la configuración observada. No equivalen a una garantía de que macOS no vuelva a bloquearse ni a una validación musical de la nueva ventana del separador.
