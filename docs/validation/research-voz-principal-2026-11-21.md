# Separación de voz principal: interrupción MPS y piloto CPU

Se preparó una alternativa al UVR Karaoke 2 ya medido: el checkpoint [BS Roformer Karaoke de Frazer y Becruily](https://huggingface.co/becruily/bs-roformer-karaoke/tree/0d66103c6b79c0dd0e9efd38ca70db7042f6f695). El intento MPS se interrumpió sin canciones completadas. Posteriormente, **Amorfoda completó una separación CPU de toda la grabación**, con memoria del trabajador monitorizada y salida finita de duración exacta. Aún falta la comparación musical de mapas; este modelo no se incorpora al producto.

El archivo de 204.436.907 bytes tiene SHA-256 `eb90ee24c1154d83fbcfd27e96182f19e061557cc6e4746953125e08c29389f9`. La carga estricta con la [implementación pública fijada](https://github.com/ZFTurbo/Music-Source-Separation-Training/tree/1523206d12a521bdb20673726562524cf0f9635b) admite 699 tensores y unos 51,05 millones de parámetros. El código declara MIT; la ficha del checkpoint no declara una licencia de pesos. La inspección y descarga permanecen como material local de investigación.

El plan fijado antes del audio conserva cuatro grabaciones ya usadas en desarrollo: Amorfoda, 11 y 6, Mr. Fancy Pants y Northern Star. La intención era comparar GAME libre recién ejecutado sobre la voz original de HTDemucs y sobre la nueva salida, compartiendo letra predicha, reloj y parámetros. Ningún mapa humano entra en la separación. El plan original usaba las ventanas publicadas de 20 segundos, cuatro solapamientos y 44.100 Hz, con lote de uno y sin precisión mixta. Se conserva intacto en `build/generation-next/lead-vocals/predeclared-plan.json`; el adaptador original se conserva en `pilot/source-v1.py`, con SHA-256 `c4cb91f68f40d55a290daf9404d7bee961bffc5072a9f2d900142d91b532cee9`. El [adaptador actual](../../scripts/experiments/lead_vocals.py) incorpora las restricciones descritas más abajo.

## Control corto e interrupción

Un control sintético de dos segundos terminó antes del reinicio del Mac comunicado por el usuario. CPU y MPS produjeron la misma forma de salida, con diferencia RMS de `1,87e-8` y máxima de `1,07e-7`. Cumple el criterio de paridad numérica fijado, pero **no prueba que las ventanas de veinte segundos sean viables en memoria**.

Al recuperar la sesión no había ningún proceso de separación vivo y sólo existía `pilot/probe.json`. Se inició el piloto MPS; en cuanto se recibió la información del reinicio se enviaron SIGINT, SIGTERM y SIGKILL al nuevo proceso. Su último punto observado era la primera invocación de `demix` de Amorfoda. No había archivos WAV de salida ni registros de canciones completadas. El proceso siguió figurando temporalmente como `?E`, con CPU y RSS a cero. Posteriormente la sesión de ejecución 81783 devolvió salida 143; los PID 4477 y 4478 ya no aparecen en `ps`.

El log del intento reanudado es `build/generation-next/lead-vocals/pilot-separation.log`, con SHA-256 `375e998c6ba6991eb4e017f588aae84fbf109f6b682aa64d5e10425d2c48468a`. La secuencia de señales y el primer snapshot permanecen en `pilot/interruption-after-reboot.json`; el fragmento de log correspondiente a su hash se conserva en `pilot/interruption-log-snapshot.txt`. El estado final está en `pilot/termination-after-reboot.json`. `/usr/bin/time -l` registró 227,48 segundos de tiempo real, RSS máximo de 942.161.920 bytes y **huella máxima de memoria de 15.516.288.440 bytes (14,45 GiB)**. Son medidas distintas; el RSS por sí solo no representa toda la huella observada durante este intento.

No se iniciaron más inferencias MPS de este ensayo. Tras recuperar memoria y cerrar sus procesos, se autorizó únicamente el control sintético CPU descrito más abajo. La correlación del reinicio con los registros del sistema está en [el informe del incidente](reinicio-experimento-2026-11-21.md). El intento reanudado y su huella final ocurrieron después del reinicio; sus medidas no demuestran por sí solas la causa del reinicio anterior.

La revisión estática identifica un límite importante: pasar de dos a veinte segundos multiplica aproximadamente por cien el tamaño de una matriz de atención temporal densa. Con unas 1.723 posiciones, 62 bandas y ocho cabezas, una matriz float32 ocuparía cerca de 5,9 GB. La [implementación de atención](https://github.com/ZFTurbo/Music-Source-Separation-Training/blob/1523206d12a521bdb20673726562524cf0f9635b/models/bs_roformer/attend.py) llama a `scaled_dot_product_attention` y selecciona explícitamente optimizaciones CUDA; la ruta MPS no tiene una comprobación propia del coste de esa ventana. Es una estimación de un riesgo de recursos identificado en el código. La huella medida durante el intento reanudado refuerza la necesidad de limitar ese experimento, sin aislar el origen de cada asignación ni establecer una explicación definitiva del reinicio.

## Plan v2 y protecciones verificadas sin inferencia

Se preparó `build/generation-next/lead-vocals/pilot-cpu-v2/plan-v2.json`. Este directorio conserva el plan con timeout de 900 segundos y una copia exacta del adaptador, sin audio generado ni prueba de modelo. El SHA-256 del adaptador fijado es `f8e733203d83ac7cdf79c2824f6e91f97442b04760c22167b74a523a9b66d65c`. Se conserva como `source-v2.py` en ambos directorios v2. Los archivos del ensayo v1, incluido su control de dos segundos, permanecen intactos.

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

## v3: memoria del trabajador durante una canción

El nuevo plan está en `build/generation-next/lead-vocals/pilot-cpu-v3/plan-v3.json`, con adaptador SHA-256 `5cc80cefe57a4088701dc3ea1e9bfa2be3ee5120754c4d6a702ccf184ed3ef97`, archivado en `source-v3.py`. Conserva las cuatro canciones del plan original, CPU con dos hilos, ventanas de cuatro segundos y timeout de 900 segundos. La opción `--only bad-bunny-amorfoda` ejecuta únicamente esa canción y no publica manifiestos que aparenten una cohorte completa.

El supervisor consulta el PID del trabajador con `proc_pid_rusage` y `RUSAGE_INFO_V0`. Se comprobaron firma, estructura de 96 bytes y campos contra los headers locales del SDK de Apple. Los campos `ri_resident_size` y `ri_phys_footprint` se guardan cada 50 ms aproximadamente. La API y los campos están en [libproc.h](https://github.com/apple-oss-distributions/xnu/blob/main/libsyscall/wrappers/libproc/libproc.h) y [resource.h](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/resource.h); Apple también muestra cómo obtener footprint mediante esa API en [WWDC22](https://developer.apple.com/videos/play/wwdc2022/10106/).

Al observar RSS o footprint de al menos 1,5 GiB, el supervisor envía SIGKILL, recoge al trabajador y detiene la tanda. Si pierde la lectura de memoria también termina el proceso. El margen nominal hasta 2 GiB es de 512 MiB, pero **el corte por muestreo no impone un límite de asignación del sistema operativo, puede omitir picos entre muestras y no garantiza la estabilidad del sistema**. Se registra el máximo observado y cada muestra, sin presentarlos como pico absoluto.

Antes de cargar el modelo pasaron 15 tests (0,53 s), Ruff y una revisión independiente. Incluyen un proceso ordinario con 32 MiB de memoria, límites simulados sin asignar grandes buffers, recogida tras pérdida de monitor y selección de una sola canción dentro de la cohorte. Al iniciar Amorfoda, el Mac permanecía silenciado; había 1,51 GiB wired, 1,71 GiB libre más especulativa y 5,24 GiB inactiva. No se ejecutó otro modelo en paralelo.

### Amorfoda completa: resultado técnico

La separación terminó con salida 0 y el PID 6960 recogido, sin alcanzar el corte preventivo ni el timeout. Se volvió a leer el WAV para comprobar que todos sus valores son finitos, su hash coincide con el registro congelado y conserva exactamente el número de muestras del HTDemucs original. No se reprodujo el audio y el Mac siguió silenciado.

| Medida | Resultado |
| --- | --- |
| Duración del audio original y separado | 7.799.297 muestras a 44.100 Hz; 176,854807 s |
| Archivo separado | Mono float32; todas las muestras finitas |
| Tiempo de separación | 532,968 s |
| Tiempo total del comando supervisado | 534,43 s; aproximadamente tres veces la duración de la canción |
| Muestras de recursos del trabajador | 10.285 |
| RSS máximo observado por el monitor | 1.353.056.256 bytes; 1.290,38 MiB |
| Huella física máxima observada por el monitor | 1.267.009.264 bytes; 1.208,31 MiB |
| Margen de RSS respecto al corte preventivo | 257.556.480 bytes; 245,63 MiB |
| Intervalo mediano / máximo entre muestras | 51,80 / 59,92 ms |
| RSS máximo de `/usr/bin/time -l` | 1.353.072.640 bytes; 16 KiB más que el máximo muestreado |

La diferencia entre el RSS informado por el sistema y el muestreado ilustra por qué se conserva la distinción entre ambos. La huella física de la tabla procede del PID de inferencia mediante libproc; no se utiliza la huella del supervisor exterior como sustituto de la del modelo. El resultado acredita esta ejecución completa de Amorfoda en el Mac M4 con CPU y estas ventanas; no acredita estabilidad en todos los equipos ni mejora de notas o letra.

La salida está en `pilot-cpu-v3/audio/bad-bunny-amorfoda.wav`, SHA-256 `11ebd8980153f04e9795811081d1d547abbdf938286b1de86a67d1caa0dd97bd`. La voz HTDemucs de entrada tiene SHA-256 `5d45cbae16b328685d13997060bc7fe46337e8beeb924933e26a586a1d91bf92`. `assessment-amorfoda.json` conserva la validación y los hashes del plan, ejecución, muestras y logs; `separation/bad-bunny-amorfoda.json` conserva la procedencia del modelo y audio, y `execution/bad-bunny-amorfoda.resources.jsonl` conserva todas las muestras de memoria. No se lanzó otra canción al terminar.

## Memoria de GAME antes de la comparación pareada

La primera ejecución GAME del audio original, con el plan `paired-cpu-v4`, fue detenida por el supervisor al alcanzar el umbral de 1,5 GiB. El proceso terminó con código −9, sin mapas finales; no hubo otro reinicio del Mac. El plan, la fuente y los registros de esa ejecución se conservan. Esta interrupción corresponde al extractor GAME posterior a la separación completa, no a una repetición del separador BS Roformer.

La [documentación de ONNX Runtime](https://onnxruntime.ai/docs/get-started/with-c.html) explica que, por defecto, cada sesión tiene una arena de memoria CPU propia y retiene sus asignaciones. Varias sesiones pueden acumular bloques que ya no necesitan activamente. GAME mantiene cinco sesiones, por lo que esta política es una explicación plausible de consumo evitable; todavía no demuestra cuánto del pico observado procede de las arenas. La [API de Python](https://onnxruntime.ai/docs/api/python/api_summary.html) permite desactivar `enable_cpu_mem_arena` y `enable_mem_pattern`.

Se añadió a `conditioned_notes.py` la opción explícita `--onnx-memory-policy no-arena`, que desactiva únicamente esas dos opciones en las cinco sesiones. La opción predeterminada conserva la política anterior. Se mantienen reutilización de buffers, optimización de gráficas, proveedor CPU, hilos, seed, modelos y ventanas; la procedencia de los resultados registra la nueva política. El adaptador previo `b3423205ac037b317bd902ef7faaf299f615a0cb6706002dd3fe317bd317a8fd` permanece en el snapshot v4; la versión preparada tiene SHA-256 `a2db868f2cf3f2442af71aa770da3868187086b8ca3ccf0118310a4cba8872a7`.

Un control con `SessionOptions` real de ONNX Runtime 1.32.0, bloqueando creación de modelos y cambios de seed, comprobó que sólo difieren esas dos opciones. Los AST de las funciones de inferencia, anclajes y duraciones coinciden con v4. La evidencia está en `onnx-memory-controls/session-options.json`; Ruff y la comprobación del diff pasan. No se ejecutó ningún modelo para este control. La regresión sobre el audio original y sus resultados congelados debe comprobar equivalencia numérica y memoria real antes de aceptar la nueva política; requiere un plan pareado nuevo y mantiene el corte preventivo del supervisor.

### Prueba pareada v5: detenida en la primera entrada

Se congeló `paired-cpu-v5/plan.json` antes de ejecutar, SHA-256 `653addc0f666cd6f89b00ade0f4c85a6e55c8fda2c593b99b18e9a050efbaaca`, conservando los cuatro IDs, seed 113, ventanas y parámetros de GAME. El plan seleccionaba sólo Amorfoda, primero original y después separada si la primera ejecución terminaba correctamente, con `--onnx-memory-policy no-arena`, timeout de 150 segundos y el mismo corte de 1,5 GiB. El snapshot v4 y la separación CPU anterior permanecieron intactos.

La entrada original volvió a superar el corte: PID 8478, estado `memory-limit`, salida −9, proceso recogido y 16,902 segundos hasta el cierre. No se elevó el límite ni se reintentó v5 para intentar obtener una predicción; posteriormente se autorizó la única ejecución instrumentada que se describe abajo para localizar la fase de crecimiento. El supervisor registró 326 muestras, RSS máximo observado de 1.615.052.800 bytes (1.540,23 MiB) y huella física de 1.578.764.232 bytes (1.505,63 MiB); fue el RSS el que activó el corte. La muestra que lo detectó está 4,23 MiB por encima del umbral, dentro de la limitación ya advertida del control por muestreo.

No se iniciaron la entrada separada ni otras canciones, y no hay mapas o trazas finales congeladas de v5. Por ello tampoco se compararon TXT con la predicción histórica ni se consultaron referencias humanas. `paired-cpu-v5/assessment-stopped.json` conserva los hashes y el estado final; `execution/original-bad-bunny-amorfoda.resources.jsonl` conserva las muestras. El Mac siguió silenciado y se liberó el turno de modelos.

**Desactivar arena y patrones no fue suficiente para completar GAME bajo el límite fijado.** Estos ensayos truncados no permiten comparar sus picos completos, acreditar equivalencia numérica ni evaluar una mejora musical. La separación completa de Amorfoda sigue siendo un resultado técnico válido; su comparación de notas permanece pendiente.

### Diagnóstico de fases, sin cambiar la configuración musical

Un launcher externo en `game-phase-diagnostic` envolvió las llamadas existentes y escribió JSONL con `flush` antes y después de `load_engine`, cada `InferenceSession` y cada `backend.extract`. Registró RSS y huella del mismo PID mediante libproc. El wrapper pasó un control sin modelos que comprobó devolución del mismo objeto y propagación de errores. El plan y el snapshot conservaron el adaptador `a2db868f…`, semilla, ventanas, pesos y límites de v5. Se ejecutó una única entrada original; no se ejecutó la separada ni se consultaron referencias.

| Fase completada | Tiempo desde el inicio de la traza | RSS |
| --- | --- | --- |
| `load_engine` | 0,023 s | 57,74 MB |
| Cinco sesiones ONNX listas | 0,618 s | 526,78 MB |
| Primera ventana de 15 s | 4,715 s | 1.066,04 MB |
| Segunda ventana de 15 s | 8,782 s | 1.244,32 MB |
| Tercera ventana de 15 s | 12,866 s | 1.435,89 MB |

El corte ocurrió **dentro de la cuarta llamada a `backend.extract`**, que había comenzado con 1.435,91 MB de RSS. El PID 8696 terminó con salida −9 y fue recogido; transcurrieron 16,848 s. El máximo muestreado fue 1.616.527.360 bytes de RSS y 1.580.173.256 bytes de huella física. Los imports y la carga inicial de las cinco sesiones no alcanzan por sí solos el presupuesto; el crecimiento observado ocurre entre ventanas. Esta traza todavía no distingue qué operador interno, referencias vivas o caché del asignador lo retiene. `game-phase-diagnostic/assessment.json` conserva hashes, fases y estado final.

Después de cerrar esa ejecución se hizo explícita la codificación UTF-8 en los seis accesos de texto de `conditioned_notes.py`. Una comprobación de ruta y contenido Unicode pasó; los AST de inferencia y opciones no cambiaron. El SHA posterior es `a2a6290ec7015dbf2f256b25f544b81a86ef897bb352dc5fe4c07b80eb3ed720`. Las fuentes ejecutadas anteriores permanecen en sus snapshots; la versión UTF-8 todavía no se ha usado para otro modelo.

### Control pequeño del asignador, sin modelos

El SDK local y la [cabecera pública de Apple](https://github.com/apple-oss-distributions/libmalloc/blob/main/include/malloc/malloc.h) documentan `malloc_zone_pressure_relief(NULL, 0)`: solicita al asignador un esfuerzo de liberación en todas sus zonas y devuelve los bytes liberados. No promete recuperar buffers aún vivos ni reducir RSS. La revisión independiente confirmó la firma y los límites. [NumPy](https://numpy.org/doc/stable/reference/c-api/data_memory.html) admite cachés y asignadores de datos configurables; esta instalación informa `default_allocator`. La documentación de [ONNX Runtime](https://onnxruntime.ai/docs/performance/tune-performance/memory.html) también contempla asignadores alternativos. Esas fuentes no bastan para atribuir a una capa concreta la memoria retenida por GAME.

Se hicieron mediciones separadas de liberación de referencias, `gc.collect()` y la API de Apple, usando sólo 32 MiB de arrays NumPy y ningún modelo. Tras eliminar las referencias, RSS permaneció en 68.845.568 bytes y huella en 55.886.328 bytes. `gc.collect()` encontró cero objetos y no redujo esas medidas; `malloc_zone_pressure_relief(NULL, 0)` devolvió cero y tampoco las redujo. El [recolector de Python](https://docs.python.org/3.12/library/gc.html) y el alivio del asignador actúan en capas distintas; se registraron por separado para no atribuir al uno el efecto del otro.

La evidencia está en `onnx-memory-controls/malloc-pressure-relief-control.json`. Este control pequeño **no demuestra una solución para GAME ni identifica la memoria retenida allí**. No se añadió alivio de memoria a `extract`, no se aislaron ventanas en procesos separados y no se ejecutó otra inferencia para probar esas alternativas.

### Configuración nueva preparada: un proceso por ventana

Se preparó el adaptador separado [windowed_game.py](../../scripts/experiments/windowed_game.py), SHA-256 `23ab26acc914e5782f479d7b578ba3cf4d38bd9353d318b5cefa19813194bf7e`, sin ejecutar modelos. El padre llama a `conditioned_notes.infer` y `transform` existentes mediante un backend que guarda exactamente el array mono float32 recibido en NPY y abre un hijo para una sola llamada a `backend.extract`. Se conservan selección de ventanas, contexto, filtrado de pertenencia, ensamblado y proyección de notas. El padre no crea sesiones ONNX ni carga modelos.

**Cada ventana reinicia la semilla 113 en un proceso nuevo.** Esta política aparece en plan, petición, respuesta y procedencia, y es igual para las voces original y separada. Es una configuración musical nueva: no se presupone equivalencia con la secuencia aleatoria continua del histórico. La comparación válida será entre ambos brazos bajo este mismo esquema, congelados antes de consultar referencias.

Cada hijo conserva el supervisor `5cc80cef…`, corte de 1,5 GiB y timeout de 30 segundos. El padre tiene un temporizador real de 900 segundos por brazo; timeout global, SIGTERM o Ctrl+C interrumpen el supervisor interior, que recoge el hijo activo. Se registra el RSS máximo del padre mediante `rusage`; sus snapshots inicial/final de huella se distinguen de un pico completo. Un fallo detiene la tanda y no se reintenta la ventana automáticamente. Las ventanas completas se pueden reutilizar sólo con hashes y estado de ejecución correctos.

Los pedidos NPY/JSON, resultados locales, estados, muestras de recursos y hashes quedan separados por ventana. Se verificaron seis controles sin modelos: transporte exacto y reutilización, rechazo de reintento tras fallo, reinicio de seed antes del segmenter, igualdad del ensamblado existente con un backend simulado, interrupción global con recogida de un hijo ordinario y preservación de un plan incompatible. Junto con los quince controles del supervisor pasan 21 tests en 0,64 s; Ruff y revisión estática independiente también pasan.

`paired-window-cpu-v6/pair-plan.json`, SHA-256 `d8548a9cbddd658d845eacc4a450a5a3394d5fc3a394c6eb33ae56915bdc7782`, conserva la cohorte original de cuatro canciones, selecciona sólo Amorfoda y mantiene 40 como denominador general. Los planes de ambos brazos y los comandos están preparados, **sin inferencia ejecutada**. Original se ejecutará primero; la voz separada sólo después de que termine correctamente. La carga de sesiones medida previamente añade unos 0,6 segundos por ventana frente a unos 4,1 segundos de extracción; estimar 70–90 segundos por brazo es orientativo, todavía sin medición de este adaptador. Una ventana distinta puede superar el límite, y el reinicio de la secuencia aleatoria puede cambiar las notas.

## Trabajo pendiente antes de comparar calidad

1. Cuando quede libre el turno de modelos, probar la configuración nueva de procesos por ventana, primero original y después separada sólo si el primer brazo completa. Congelar ambos resultados antes de evaluar; no elevar el límite preventivo ni afirmar equivalencia numérica con el histórico.
2. Revisar calidad y coste de esta primera canción antes de decidir sobre las otras tres del plan; ninguna ejecución debe competir con otro modelo. La cohorte originalmente declarada sigue siendo de cuatro canciones y sólo una tiene separación completa.
3. Decidir a partir de notas, duraciones, cobertura y letra si existe mejora reproducible. Cualquier adopción o distribución de pesos exige además resolver la licencia de éstos.

El ensayo queda sin evidencia de mejora de letra, notas o duración. El control corto, la compatibilidad de pesos y la disponibilidad del modelo no sustituyen esa validación.
