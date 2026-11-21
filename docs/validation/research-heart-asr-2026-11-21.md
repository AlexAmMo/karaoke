# Heart ASR: cuatro canciones evaluadas, sin ampliación

La comparación acústica de cuatro grabaciones completas **no justifica ampliar Heart a las otras 36 identidades**. Frente al Turbo `vocals-native` fijado como baseline, el WER del texto que conserva la app pasa del **27,705 % al 36,980 %**: aumenta un **33,48 % relativo**. Mejora Mr. Fancy Pants y empeoran las otras tres canciones; la mediana pasa del 20,700 % al 31,943 %. Ninguna de las cuatro salidas Heart alcanza WER ≤ 5 %, y no se generaron nuevos mapas musicales.

Las cuatro condiciones Heart finalizaron técnicamente con salida 0, procesos recogidos y archivos congelados antes de evaluar. El texto crudo, previo al filtro productivo, tiene un WER agrupado del **55,886 %**, frente al 28,062 % de Turbo. Se conservan todos los resultados y repeticiones. El plan seleccionado fue v2 con el entorno Heart independiente; v1 permanece sin ejecutar. La evaluación y su exportación ya están auditadas.

La propuesta previa `build/generation-next/heart-cpu-research/execution-proposal-fp16-pread-v2.json`, SHA-256 `d8e8951e071720bb741d6f19aeb0aeb59fb666f588041a8aa3367780cb013d15`, fija la variante: origen oficial HeartTranscriptor, conversión FP32 → FP16 mediante lectura pread → CTranslate2 int8, CPU, dos hilos, un trabajador y una canción a la vez. La conversión puede cambiar valores respecto de cuantizar directamente FP32. La comparación es entre cadenas completas —pesos, conversión, opciones y ejecución—, no una prueba aislada de los pesos ni equivalencia con la implementación del autor.

## Condiciones fijas y reloj

Se reutilizan, sin recodificar, las cuatro ondas vocales mono de 16 kHz de RMS: Amorfoda, 11 y 6, Mr. Fancy Pants y Northern Star. El plan verifica sus hashes, número de muestras, canales, frecuencia, valores finitos y señal no nula. Conserva el enlace al máster original y a la voz separada. La referencia de comparación es exclusivamente Turbo `vocals-native`; no se selecciona un brazo RMS por canción. La propuesta histórica conserva enlaces antiguos a v2, pero el plan nuevo exige expresamente RMS **v3**, su freeze completo y las cuatro predicciones vocales correspondientes.

Heart recibe cada canción completa con segmentación nativa de 30 s, `beam_size=2`, `best_of=1`, temperaturas `[0, 0.1, 0.2, 0.4]`, umbral de compresión 1,8, log-probabilidad −1, ausencia de voz 0,4 y máximo de 256 tokens nuevos. Usa tiempos de palabra, VAD desactivado, texto previo desactivado e idioma fijo es/en. La semilla de CTranslate2 es 113. El Turbo histórico no había fijado una semilla; no se afirma que los caminos de muestreo sean equivalentes si se activa la temperatura de respaldo.

Se reutiliza `generation_worker.transcribe` para el remuestreo y los filtros de palabra del producto. Un envoltorio valida su llamada y sustituye **todos los argumentos de decodificación** por los de Heart: el `beam_size=5` interno de producción no llega al reconocedor. Registra argumentos recibidos y efectivos, y copia los segmentos crudos antes de filtrar. Conserva signos, repeticiones, palabras de duración no positiva y cruces de frontera en la vista cruda; las líneas filtradas se guardan aparte. El control simulado confirma que la onda preparada llega idéntica y que el reloj absoluto no cambia.

El plan fija la fuente de producción actual, que ya incorpora la guardia de silencio posterior a RMS. Las cuatro ondas y el control Heart son no nulos; no se modifica la fuente congelada ni se vuelve a ejecutar Turbo v3. Los tiempos ASR obtenidos no se presentan como una alineación forzada final ni como finales correctos de notas musicales.

## Procedencia y supervisión

El plan firma propuesta, adaptador, ayudantes RMS, función de producción, supervisor, monitor, conversión, modelo convertido, entradas y baseline. El consumidor de la conversión comprueba su plan, salida exitosa, recogida, manifiesto del trabajador y hashes de los archivos convertidos, sin cargar tensores. El modelo usa archivos locales y modo offline. Las versiones fijadas de inferencia son faster-whisper 1.2.1, CTranslate2 4.9.0, NumPy 2.5.5, SciPy 1.18.1 y SoundFile 0.14.0.

El comando `synthetic` crea dos segundos de señal finita no nula: seno de 440 Hz con armónico de 880 Hz y envolvente suave, mono a 16 kHz. No se reproduce por altavoces. Tiene cuota de **4 GiB** y plazo de **120 s**, y sólo comprueba carga, opciones, captura y serialización. Una letra reconocida en esa señal no demostraría precisión de canto. Sólo una salida exitosa y recogida produce `synthetic-frozen.json`.

El comando `execute` exige ese control del mismo plan. Después inicia cuatro procesos frescos y secuenciales, cada uno con **4 GiB y 900 s**. El supervisor muestrea RSS y huella física cada 50 ms; mata y recoge ante superación, pérdida de telemetría, plazo o interrupción. El controlador detiene la cohorte al primer fallo, conserva archivos parciales y no reintenta ni aumenta cuota. `frozen.json` sólo aparece tras las cuatro salidas correctas y recogidas. Los límites son supervisión por muestras, no topes de asignación impuestos por el sistema.

Antes de inferir no se disponía de una duración medida para Heart. Los cuatro plazos sumaban 60 minutos, más el control de 120 s; eran máximos de supervisión, no un tiempo esperado. La medición final de las cuatro canciones fue 348,312 s y permanece separada del control sintético y la conversión de pesos.

## Controles sin modelos y contrato de evaluación

El `selftest` pasó nueve controles ligeros en `build/generation-bench/env`: señal sintética no nula, reloj exacto, opciones Heart efectivas, filtros productivos y repeticiones, dataclasses anidadas y escalares NumPy, indicadores de frontera, rechazo de NaN/infinito/objetos arbitrarios, rechazo de cambios en la llamada de producción y ausencia de imports de Torch/faster-whisper/CTranslate2. La serialización conserva precisión y campos, exige `allow_nan=False` y valida todo antes de crear el archivo inmutable.

En `tests/test_heart_asr.py` pasan nueve pruebas adicionales de enlace de conversión, alteraciones de evidencia, propagación de cuota/plazo, rechazo de reintentos, parada al primer fallo y ausencia de freeze sin recogida. El décimo caso invoca el mismo control de audio: se omite en el entorno básico de la app porque no instala SciPy, y **sí se ejecutó correctamente** mediante el `selftest` en el entorno de investigación. Ruff y `git diff --check` pasan. No se cambió producción.

El contrato acordado con `heart_asr_evaluate.py` usa `heart-native` frente a `turbo-vocals-native`, sin elegir por canción. Cada predicción contiene identidad, hash de plan, audio, `raw_words`, `product_lines` e intervalos del reloj original. La congelación final conserva predicción, recursos y todos los archivos parciales por canción. El evaluador separado exige los cuatro candidatos completos, valida globalmente la procedencia antes de leer referencias y conserva 40 identidades por brazo: 80 condiciones y 160 filas al separar vistas cruda/productiva. El protocolo de evaluación real se firma por separado después del plan y antes de ejecutar el control; no altera sus predicciones ni lee letras de referencia en esta fase.

```sh
# Ejecutado: control ligero, sin cargar un modelo.
build/generation-bench/env/bin/python scripts/experiments/heart_asr.py selftest
uv run pytest -q tests/test_heart_asr.py

# Preparación histórica v1, creada y verificada pero nunca ejecutada:
build/generation-bench/env/bin/python scripts/experiments/heart_asr.py plan \
  --conversion-freeze build/generation-next/heart-transcriptor/conversion-v2/frozen.json \
  --output build/generation-next/heart-asr/v1

# El plan v1 se conserva sin ejecutar; el control usa el nuevo plan v2.
```


## Preparación v1 conservada sin ejecutar

La conversión v2 terminó con salida 0 y recogida confirmada. Su freeze `c9827e4989869d5a870b6b8a4bdac23914e680fcaed59936f0e7150ea33a2d41` fija los cinco archivos CT2 consumidos por el plan de reconocimiento. El plan `build/generation-next/heart-asr/v1/plan.json`, SHA-256 `499a4b9c6030951f5d48c0518415303f6340d7f48bc437995c185497e4dcf73a`, conserva el adaptador revisado `b68b3b77aeb8446f1dee27357ed433964ff6d77e92cd10d03c341a5752fe1dc7`, cinco snapshots de código, modelo convertido, baseline v3, cuatro WAV y todas las opciones previas.

`preflight-audit.json` (`ca283a4d6b01089e78a90ee25051b332ff4666cd0fbcd8094cb25aaa8ac1e13f`) volvió a comprobar archivos, snapshots, identidades, opciones y versiones del entorno de inferencia, sin importar runtimes de modelos ni abrir referencias. En v1 no existe intento de control ni carpeta de resultados. El criterio de ampliación quedó fijado antes de ASR en `heart-transcriptor/expansion-decision-before-asr.json`: cuatro parejas completas, reducción relativa WER agrupado ≥ 10 %, mediana inferior, al menos tres canciones sin empeorar y dos mejores, y ningún retroceso superior a 2 puntos porcentuales. No sustituye los criterios de mapas ni de fiabilidad casi perfecta.

El protocolo real `heart-asr/v1/evaluation-protocol.json` quedó firmado antes de inferencia con SHA-256 `c71d9e6325860f25a2dde35a5f9dfc3418e4379b06e9044e2df3554e55863634`. Enlaza el plan v1, el baseline histórico y el medidor común, y mantiene las dos vistas y las 40 identidades por brazo. La revisión independiente `evaluation-pre-inference-review.json` enlaza además el criterio previo de ampliación y comprueba que todavía no existían controles, resultados ni freeze de generación. No se abrió el texto de referencia.


## V2: entorno independiente, mismas condiciones

La revisión del coordinador detectó que el CLI había fijado en v1 `/Users/ton/Desktop/Karaoke/build/generation-bench/env/bin/python`, por ser el intérprete que creó el plan. Aunque sus versiones de inferencia coincidían, el protocolo operativo acordado utiliza el entorno Heart independiente para conversión e inferencia. **No hubo control ni resultados en v1**; se preservan su plan, protocolo y auditoría como preparación histórica.

El nuevo plan `build/generation-next/heart-asr/v2/plan.json` tiene SHA-256 `aa46ae5163621074b83afc8931556771e104098c196dc4c124225d8a1907c28f` y fija `/Users/ton/Desktop/Karaoke/build/generation-next/heart-transcriptor/env/bin/python`. `v2/plan-review.json` (`d62ceeadd8dc1f575c3292d58e22e90e979c5e7b1212b1b103594c6c52fb6cee`) comprueba que **sólo cambiaron `python` y `created_utc`** respecto de v1. El lock del entorno de 35 paquetes tiene SHA-256 `880cca28f091287ee8b96ff83823649416c824329d3b51e3fd65fae2ca92fbb5`.

El protocolo de evaluación v2 también se fijó antes de inferir: `9fafdd8d073978f5f860871441331681c4e451d4e3d6e2f78919191fa66e0fde`. Las reglas de evaluación y ampliación, los cuatro WAV, la conversión congelada, el adaptador, las opciones Heart y los presupuestos se mantienen. El control se ejecutó por separado antes de la tanda de canciones. Ambas fases conservan sus archivos y recursos; completar el control no autoriza a interpretar su texto como letra correcta.


## Control sintético v2 completado

El único control sintético v2 terminó con salida 0, recogida confirmada y PID 16507 ausente. Duró **41,748 s** y alcanzó máximos muestreados de **1.600,828 MiB RSS** y **1.558,033 MiB de huella física**, por debajo de 4.096 MiB. Su freeze tiene SHA-256 `cc58537c79b8dbabd9bf6990d09a175d6cb266294955ba01060514f5823af0a9`; los archivos y hashes fueron comprobados por el coordinador.

El tono sintético sin habla produjo **10 palabras crudas y 6 conservadas por el filtro de producción**. Es una alucinación observada sobre ese control, no un éxito de precisión ni un WER de canto. El control verifica viabilidad de carga, inferencia y serialización bajo esta configuración; no demuestra la memoria máxima de canciones completas ni calidad de letras.

Después se inició `execute` con el mismo plan v2, CPU int8 y dos hilos, cuatro procesos secuenciales y límite de 4 GiB/900 s por canción. Se verificó `output muted=true` en el Mac y no se leyó ninguna referencia. La evidencia de esta fase se conserva en `v2/results/` y `cohort-launch.log`; no se cambiaron parámetros ni se repitió ninguna canción. Los avisos automáticos del runtime sobre otros dispositivos no alteran el `device=cpu` fijado en el plan.


## Cohorte v2: cuatro canciones completadas y congeladas

La ejecución secuencial terminó sin errores, cortes ni reintentos. Los cuatro trabajadores finalizaron con salida 0 y recogida confirmada; una consulta posterior de sus PID comprobó que ninguno seguía presente. El Mac permaneció silenciado. Se verificaron **40 registros de salida**, incluidas predicciones, recursos y evidencias parciales, junto con las identidades, el reloj de muestra completa y los argumentos Heart efectivos. Las palabras crudas y líneas de producto coinciden exactamente con las conservadas en cada fragmento.

| Grabación | Tiempo supervisado (s) | Máximo RSS observado (MiB) | Máxima huella física observada (MiB) | Estado |
|---|---:|---:|---:|---|
| Amorfoda | 83.974 | 1767.656 | 1724.783 | salida 0, recogido |
| 11 y 6 | 102.780 | 1746.750 | 1703.799 | salida 0, recogido |
| Mr. Fancy Pants | 67.421 | 1651.422 | 1608.486 | salida 0, recogido |
| Northern Star | 94.136 | 1688.125 | 1645.127 | salida 0, recogido |

La suma de tiempos supervisados es **348,312 s (5 min 48 s)**, excluidos los pequeños intervalos del controlador. El máximo observado fue **1.767,656 MiB RSS** y **1.724,783 MiB de huella física**. Hubo 6.552 muestras, intervalo mediano de 52,809 ms y máximo de 58,490 ms. Son recursos medidos en el Mac M4 real, CPU y audios guardados; no una medición de voz en directo ni una cota sobre picos entre muestras.

El freeze de generación `v2/frozen.json` tiene SHA-256 `c80a5daa74cfe43c64389175ed768c1b8949fa90f99a9506b0c5155a4452f6bd`. La auditoría técnica `v2/cohort-assessment.json` tiene SHA-256 `67d4507f4e9a9ebca73c270783b32246de82d0fef0ce8b3145914df02a187ed6` y conserva el cierre, hashes, recursos, cantidades de palabras y denominador de 40 identidades. No abrió referencias ni calculó precisión. El proceso de modelos quedó libre antes de notificar al coordinador para congelar las entradas de evaluación y comparar las letras por separado. Completar estas cuatro ejecuciones acredita el cierre técnico; la evaluación siguiente no alcanza la fiabilidad buscada.


## Resultados completos de letras y tiempos

La medida primaria es WER de `product_lines`; `raw_words` es la vista adicional fijada antes de inferir. La normalización común conserva acentos y repeticiones. S/D/I/C indican sustituciones, eliminaciones, inserciones y coincidencias; N/H son cantidades de tokens de referencia e hipótesis. El WER es (S+D+I)/N. Puede superar el 100 % si hay muchas inserciones: ocurre en la vista cruda de 11 y 6; no se recorta ese valor.

La cobertura es C/N. p50/p90 miden error absoluto de inicio sólo de las palabras que coinciden léxicamente, en el reloj original y sin ajustar un desplazamiento. Estos tiempos ASR no equivalen a una alineación forzada final ni prueban la duración de notas.

| Grabación | Cadena | Vista | S/D/I/C | N/H | WER (%) | Cobertura exacta (%) | p50/p90 (ms) |
|---|---|---|---:|---:|---:|---:|---:|
| Amorfoda | Turbo | producto | 84/8/3/198 | 290/285 | 32.759 | 68.276 | 121/235 |
| Amorfoda | Turbo | cruda | 84/8/3/198 | 290/285 | 32.759 | 68.276 | 121/235 |
| Amorfoda | Heart | producto | 112/13/50/165 | 290/327 | 60.345 | 56.897 | 63/186 |
| Amorfoda | Heart | cruda | 111/11/69/168 | 290/348 | 65.862 | 57.931 | 65/188 |
| 11 y 6 | Turbo | producto | 8/0/6/154 | 162/168 | 8.642 | 95.062 | 158/1153 |
| 11 y 6 | Turbo | cruda | 8/0/9/154 | 162/171 | 10.494 | 95.062 | 158/1153 |
| 11 y 6 | Heart | producto | 15/5/48/142 | 162/205 | 41.975 | 87.654 | 120/609 |
| 11 y 6 | Heart | cruda | 16/0/163/146 | 162/325 | 110.494 | 90.123 | 121/640 |
| Mr. Fancy Pants | Turbo | producto | 5/107/0/99 | 211/104 | 53.081 | 46.919 | 66/383 |
| Mr. Fancy Pants | Turbo | cruda | 5/107/0/99 | 211/104 | 53.081 | 46.919 | 66/383 |
| Mr. Fancy Pants | Heart | producto | 10/9/10/192 | 211/212 | 13.744 | 90.995 | 86/163 |
| Mr. Fancy Pants | Heart | cruda | 10/8/26/193 | 211/229 | 20.853 | 91.469 | 86/164 |
| Northern Star | Turbo | producto | 8/2/2/168 | 178/178 | 6.742 | 94.382 | 154/696 |
| Northern Star | Turbo | cruda | 8/2/2/168 | 178/178 | 6.742 | 94.382 | 154/696 |
| Northern Star | Heart | producto | 10/4/25/164 | 178/199 | 21.910 | 92.135 | 94/710 |
| Northern Star | Heart | cruda | 11/1/44/166 | 178/221 | 31.461 | 93.258 | 96/744 |

| Cadena | Vista | Medidas / cohorte | S/D/I/C | N/H | WER agrupado (%) | Mediana WER (%) |
|---|---|---:|---:|---:|---:|---:|
| Turbo | producto | 4/40 | 105/117/11/619 | 841/735 | 27.705 | 20.700 |
| Turbo | cruda | 4/40 | 105/117/14/619 | 841/738 | 28.062 | 21.626 |
| Heart | producto | 4/40 | 147/31/133/663 | 841/943 | 36.980 | 31.943 |
| Heart | cruda | 4/40 | 148/20/302/673 | 841/1123 | 55.886 | 48.661 |

Heart recupera gran parte de las omisiones de Mr. Fancy Pants (107 → 9 en producto), pero aumenta las inserciones en las cuatro canciones. En el conjunto pasan de 11 a 133, junto con 147 sustituciones y 31 eliminaciones: **311 errores sobre 841 tokens de referencia**, frente a 233 de Turbo. El filtro productivo reduce el WER crudo de Heart del 55,886 % al 36,980 %, sin convertirlo en una letra fiable; también reduce sus coincidencias de 673 a 663. La vista cruda completa queda conservada.

El p90 productivo mejora en Amorfoda (235 → 186 ms), 11 y 6 (1.153 → 609 ms) y Mr. Fancy Pants (383 → 163 ms), pero empeora ligeramente en Northern Star (696 → 710 ms). La cobertura léxica cae en tres canciones: 68,276 → 56,897 %, 95,062 → 87,654 % y 94,382 → 92,135 %; sólo sube en Mr. Fancy Pants (46,919 → 90,995 %). Por tanto, tiempos mejores sobre menos palabras coincidentes no acreditan una letra mejor sincronizada en su conjunto.

## Decisión previa aplicada sin cambios

La regla de ampliación, firmada antes del ASR con SHA-256 `95ec076211918c993535593fad539b27333edd16a68da5bd304fc700d592fcb2`, exigía cuatro parejas completas, reducción relativa agrupada ≥ 10 %, mediana inferior, al menos tres canciones sin empeorar y dos mejores, y ningún retroceso mayor de 2 puntos porcentuales. **Sólo se cumple tener las cuatro parejas completas.** La reducción relativa agrupada es negativa (−33,476 %), mejora una canción y empeoran tres; el mayor retroceso es **+33,333 puntos** en 11 y 6. La mediana de diferencias por canción es +21,377 puntos.

La decisión es **no ampliar esta configuración ni promoverla al flujo de descarga**. No se elige la salida de Heart sólo para la canción favorable, no se cambian parámetros a partir de estas referencias y no se presenta como un resultado universal contra otros usos de Heart. Son cuatro grabaciones del piloto de desarrollo, no un conjunto reservado. Ninguna de las cuatro salidas Heart llega a WER ≤ 5 % o ≤ 1 %; no hay mapas nuevos ni evidencia de superar los cinco controles de juego casi perfecto.

## Coste comparable de ambas cadenas

Se comparan los cuatro procesos Heart con los cuatro procesos históricos Turbo **vocales/nativos**, sobre los mismos WAV en el Mac M4 real, CPU y sin reproducción audible. No se suma el resto del factorial RMS. Los tiempos incluyen carga y trabajo supervisado de cada proceso; excluyen separación de voces, conversión de pesos, controles sintéticos y evaluación. Son mediciones secuenciales históricas, no una prueba alternada diseñada para aislar cambios de carga del sistema. Heart usa dos hilos y beam 2; Turbo usaba tres hilos y beam 5, además de otros cambios de pesos y decodificación.

| Grabación | Cadena | Tiempo (s) | Máximo RSS (MiB) | Máxima huella física (MiB) |
|---|---|---:|---:|---:|
| Amorfoda | Turbo | 46.370 | 2195.609 | 2152.034 |
| Amorfoda | Heart | 83.974 | 1767.656 | 1724.783 |
| 11 y 6 | Turbo | 68.045 | 2219.016 | 2175.487 |
| 11 y 6 | Heart | 102.780 | 1746.750 | 1703.799 |
| Mr. Fancy Pants | Turbo | 20.160 | 2180.766 | 2154.299 |
| Mr. Fancy Pants | Heart | 67.421 | 1651.422 | 1608.486 |
| Northern Star | Turbo | 43.179 | 2185.156 | 2158.706 |
| Northern Star | Heart | 94.136 | 1688.125 | 1645.127 |

| Cadena | Tiempo de cuatro procesos (s) | Máximo RSS (MiB) | Máxima huella física (MiB) |
|---|---:|---:|---:|
| Turbo | 177.753 | 2219.016 | 2175.487 |
| Heart | 348.312 | 1767.656 | 1724.783 |

Heart tardó aproximadamente **1,96 veces** lo que tardó ese baseline, con menor máximo de memoria observado. Los ocho procesos incluidos terminaron con salida 0 y recogida confirmada. El muestreo de recursos no establece un techo de memoria entre observaciones. La menor memoria no compensa los retrocesos de letras bajo el criterio de ampliación fijado.

## Exportación y auditoría independiente

El [CSV íntegro](generacion-heart-asr-2026-11-21.csv) mantiene **160 filas**: 40 identidades × 2 cadenas × 2 vistas. Contiene 16 filas medidas, correspondientes a ocho condiciones, y **144 filas ausentes** para las 36 canciones no ejecutadas en cada cadena. Las ausentes tienen métricas vacías; no cuentan como WER cero ni como éxito. Las estadísticas anteriores se limitan a **4/40 por cadena**. La copia documental conserva exactamente los bytes y finales CRLF del original.

La auditoría independiente `v2/review-export.json` terminó en PASS: comprobó 52 artefactos congelados, todos los campos numéricos del CSV, las identidades S/D/I/C y WER, los percentiles temporales frente a las parejas conservadas, los resúmenes, recursos y el criterio previo de ampliación. No volvió a cargar modelos ni a abrir letras humanas para otra alineación; su alcance es la integridad y conciliación del resultado evaluado. Los planes, predicciones, métricas y umbrales permanecen intactos.

| Evidencia | SHA-256 |
|---|---|
| Entradas congeladas de evaluación | `5018192798ba7494a5afa5fb7fc0b400fdc4a90aef3cdc0333efbfa79e2b234c` |
| Evaluación JSON | `1503c4da2a9e646977638df955d1c1419f39440158bc72cd99e9a55cb34342ed` |
| CSV original y copia documental | `b2236e29e33e707d146048ecb7bb8250a6118c040d677b316c24f58d2e91021f` |
| Auditoría independiente del export | `675cd8f3f59cb0d7ebf57f13675de7bec82363c802a33886228abd2c6eb1084c` |
