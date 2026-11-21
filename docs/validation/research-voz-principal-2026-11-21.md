# Separación de voz principal: ensayo BS Roformer interrumpido

Se preparó una alternativa al UVR Karaoke 2 ya medido: el checkpoint [BS Roformer Karaoke de Frazer y Becruily](https://huggingface.co/becruily/bs-roformer-karaoke/tree/0d66103c6b79c0dd0e9efd38ca70db7042f6f695). No hay resultados musicales de este nuevo ensayo: **ninguna canción llegó a completar la separación** y no se evaluaron mapas. No se incorpora este modelo al producto.

El archivo de 204.436.907 bytes tiene SHA-256 `eb90ee24c1154d83fbcfd27e96182f19e061557cc6e4746953125e08c29389f9`. La carga estricta con la [implementación pública fijada](https://github.com/ZFTurbo/Music-Source-Separation-Training/tree/1523206d12a521bdb20673726562524cf0f9635b) admite 699 tensores y unos 51,05 millones de parámetros. El código declara MIT; la ficha del checkpoint no declara una licencia de pesos. La inspección y descarga permanecen como material local de investigación.

El plan fijado antes del audio conserva cuatro grabaciones ya usadas en desarrollo: Amorfoda, 11 y 6, Mr. Fancy Pants y Northern Star. La intención era comparar GAME libre recién ejecutado sobre la voz original de HTDemucs y sobre la nueva salida, compartiendo letra predicha, reloj y parámetros. Ningún mapa humano entra en la separación. El plan original usaba las ventanas publicadas de 20 segundos, cuatro solapamientos y 44.100 Hz, con lote de uno y sin precisión mixta. Se conserva intacto en `build/generation-next/lead-vocals/predeclared-plan.json`; el adaptador original se conserva en `pilot/source-v1.py`, con SHA-256 `c4cb91f68f40d55a290daf9404d7bee961bffc5072a9f2d900142d91b532cee9`. El [adaptador actual](../../scripts/experiments/lead_vocals.py) incorpora las restricciones descritas más abajo.

## Control corto e interrupción

Un control sintético de dos segundos terminó antes del reinicio del Mac comunicado por el usuario. CPU y MPS produjeron la misma forma de salida, con diferencia RMS de `1,87e-8` y máxima de `1,07e-7`. Cumple el criterio de paridad numérica fijado, pero **no prueba que las ventanas de veinte segundos sean viables en memoria**.

Al recuperar la sesión no había ningún proceso de separación vivo y sólo existía `pilot/probe.json`. Se inició el piloto MPS; en cuanto se recibió la información del reinicio se enviaron SIGINT, SIGTERM y SIGKILL al nuevo proceso. Su último punto observado era la primera invocación de `demix` de Amorfoda. No había archivos WAV de salida ni registros de canciones completadas. El proceso siguió figurando temporalmente como `?E`, con CPU y RSS a cero. Posteriormente la sesión de ejecución 81783 devolvió salida 143; los PID 4477 y 4478 ya no aparecen en `ps`.

El log del intento reanudado es `build/generation-next/lead-vocals/pilot-separation.log`, con SHA-256 `375e998c6ba6991eb4e017f588aae84fbf109f6b682aa64d5e10425d2c48468a`. La secuencia de señales y el primer snapshot permanecen en `pilot/interruption-after-reboot.json`; el fragmento de log correspondiente a su hash se conserva en `pilot/interruption-log-snapshot.txt`. El estado final está en `pilot/termination-after-reboot.json`. `/usr/bin/time -l` registró 227,48 segundos de tiempo real, RSS máximo de 942.161.920 bytes y **huella máxima de memoria de 15.516.288.440 bytes (14,45 GiB)**. Son medidas distintas; el RSS por sí solo no representa toda la huella observada durante este intento.

No se iniciaron más inferencias MPS de este ensayo. Tras recuperar memoria y cerrar sus procesos, se autorizó únicamente el control sintético CPU descrito más abajo. La correlación del reinicio con los registros del sistema está en [el informe del incidente](reinicio-experimento-2026-11-21.md). El intento reanudado y su huella final ocurrieron después del reinicio; sus medidas no demuestran por sí solas la causa del reinicio anterior.

La revisión estática identifica un límite importante: pasar de dos a veinte segundos multiplica aproximadamente por cien el tamaño de una matriz de atención temporal densa. Con unas 1.723 posiciones, 62 bandas y ocho cabezas, una matriz float32 ocuparía cerca de 5,9 GB. La [implementación de atención](https://github.com/ZFTurbo/Music-Source-Separation-Training/blob/1523206d12a521bdb20673726562524cf0f9635b/models/bs_roformer/attend.py) llama a `scaled_dot_product_attention` y selecciona explícitamente optimizaciones CUDA; la ruta MPS no tiene una comprobación propia del coste de esa ventana. Es una estimación de un riesgo de recursos identificado en el código. La huella medida durante el intento reanudado refuerza la necesidad de limitar ese experimento, sin aislar el origen de cada asignación ni establecer una explicación definitiva del reinicio.

## Plan v2 y protecciones verificadas sin inferencia

Se preparó `build/generation-next/lead-vocals/pilot-cpu-v2/plan-v2.json`. Este directorio sigue conteniendo únicamente el plan con timeout de 900 segundos, sin audio generado ni prueba de modelo. El SHA-256 del adaptador fijado es `f8e733203d83ac7cdf79c2824f6e91f97442b04760c22167b74a523a9b66d65c`. Los archivos del ensayo v1, incluido su control de dos segundos, permanecen intactos.

- MPS queda rechazado por completo antes de importar PyTorch, leer pesos o crear un proceso de inferencia. CPU es el dispositivo predeterminado y usa dos hilos.
- La ventana predeterminada pasa a cuatro segundos, con cuatro solapamientos y lote de uno. El control sintético también usa la ventana completa de cuatro segundos. Esta configuración difiere de los veinte segundos publicados y requiere su propia validación de calidad.
- Antes de cargar el modelo se estima el coste de tres matrices temporales, dos buffers del tamaño de los pesos y 256 MiB adicionales. Cuatro segundos estiman 1.385.746.070 bytes (1.321,55 MiB); veinte segundos superan el umbral preventivo de 2 GiB y se rechazan. **No es un límite de memoria impuesto por el sistema operativo ni garantiza el pico real.**
- Tanto el control sintético como cada canción se ejecutan en un proceso hijo con límite predeterminado de 900 segundos. El supervisor termina y recoge el proceso si hay timeout o interrupción, guarda el estado mediante reemplazo atómico y detiene la secuencia si no puede confirmar su terminación.
- Planes, predicciones y registros completos son inmutables; los WAV sólo se publican al terminar su escritura. Las canciones ya finalizadas pueden reutilizarse tras comprobar sus hashes y configuración.

Los diez tests de [test_lead_vocals_limits.py](../../tests/test_lead_vocals_limits.py) pasan en 0,26 segundos, junto con Ruff y `git diff --check`. Cubren rechazo del antiguo comando MPS y de ventanas de veinte segundos sin importar PyTorch ni SoundFile, plan sin modelo, rechazo de recursos inválidos, escritura atómica, timeout de un proceso ordinario, interrupción del supervisor y uso del supervisor en el control sintético. Una revisión independiente comprobó las protecciones. No se ha ejecutado el modelo para validarlas.

## Control sintético CPU de cuatro segundos

Con el Mac silenciado y sin otros procesos de modelos, `vm_stat` mostró aproximadamente 1,52 GiB de memoria wired, 2,83 GiB libre más especulativa y 4,96 GiB inactiva. Se creó un plan separado en `build/generation-next/lead-vocals/pilot-cpu-v2-probe-60s`, con timeout de 60 segundos y el mismo adaptador del commit `04f2945`, sin modificarlo. Se ejecutó **una sola** pasada sintética CPU de cuatro segundos bajo el supervisor existente y `/usr/bin/time -l`.

| Medida | Resultado |
| --- | --- |
| Estado del proceso hijo | `complete`, salida 0; PID 6131 recogido |
| Inferencia de la ventana de cuatro segundos | 2,911 s |
| Tiempo total del comando supervisado | 5,04 s |
| Forma de salida | `[1, 1, 2, 176400]` |
| Longitud y valores finitos | Comprobados por el hook del modelo, sin error |
| RSS máximo informado por `/usr/bin/time -l` | 1.057.406.976 bytes; 1.008,42 MiB |
| Campo `peak memory footprint` del comando exterior | 23.511.520 bytes; 22,42 MiB, **corresponde al supervisor, no mide la huella máxima del hijo que carga el modelo** |
| Estado al terminar | Mac silenciado, sin proceso hijo pendiente; ninguna canción iniciada |

El comando exterior envuelve al supervisor Python, que crea el proceso de inferencia. Por tanto, su campo `peak memory footprint` no se puede comparar directamente con los 14,45 GiB del intento MPS anterior, que se ejecutaba sin ese proceso intermedio. El RSS registrado aporta evidencia sobre este control; la huella específica del proceso hijo no quedó medida. Una próxima ejecución tendría que recogerla dentro del hijo o mediante observación directa, sin sustituirla por el valor del supervisor.

`assessment.json` conserva los tiempos, hashes, estado final y esta limitación; `cpu-probe-v2.json`, `control.log`, `logs/probe.log`, `execution/probe.json` y `preflight.json` conservan los registros originales. El adaptador comprueba que toda la salida es finita, pero no guarda su forma de onda. No se repitió la inferencia para obtener más métricas. Este resultado acredita una ventana CPU sintética de cuatro segundos; no acredita la estabilidad de una canción completa, el solapamiento de múltiples ventanas ni la calidad musical.

## Trabajo pendiente antes de comparar calidad

1. Revisar el margen observado y preparar medición de huella del proceso hijo antes de cualquier prueba más larga. El control ejecutado en esta tanda ya terminó; no se continuó automáticamente a una canción.
2. Con margen suficiente y esa medición disponible, realizar una separación completa con seguimiento de recursos y revisar su huella antes de las otras tres canciones; ninguna ejecución debe competir con otro modelo.
3. Generar las parejas GAME libres sobre HTDemucs original y voz principal nueva, usando el mismo audio de origen, reloj, letra predicha y parámetros. Congelar todos los resultados antes de acceder a las referencias humanas y evaluar con el evaluador común.
4. Decidir a partir de notas, duraciones, cobertura y letra si existe mejora reproducible. Cualquier adopción o distribución de pesos exige además resolver la licencia de éstos.

El ensayo queda sin evidencia de mejora de letra, notas o duración. El control corto, la compatibilidad de pesos y la disponibilidad del modelo no sustituyen esa validación.
