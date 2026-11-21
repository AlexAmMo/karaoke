# HeartTranscriptor en CPU: conversión y presupuesto previo

Fecha: 21 de noviembre de 2026. Continuación de [la investigación de reconocedores para canto](research-letras-siguientes-2026-11-21.md). **Existe una ruta compatible con el formato oficial, pero todavía no se ha convertido ni ejecutado HeartTranscriptor en este Mac.** La candidata seleccionada es FP32 → FP16 durante una lectura por tensor → CTranslate2 int8, seguida de CPU, lote uno, dos hilos y beam dos. El presupuesto preventivo queda por debajo de 4 GiB; es una estimación, no una medición de pico ni una garantía de estabilidad.

No se han descargado pesos, instalado dependencias, abierto referencias de letras ni ocupado el turno de inferencia. Se han leído fuentes y metadatos pequeños, comparado código instalado y hecho un control de cuatro valores sintéticos con NumPy. El Mac permanece silenciado.

## Compatibilidad de arquitectura y formato

El checkpoint oficial `HeartMuLa/HeartTranscriptor-oss`, revisión `ee842de9aeec454236badef2205dea47a1fd8410`, declara `WhisperForConditionalGeneration`: 24 capas de codificador, 24 de decodificador, dimensión 1.024, 16 cabezas y 80 bandas mel. Publica un archivo FP32 de 3.055.544.304 bytes, con SHA-256 LFS `9e09145b687c26330da96ad2d7ca1fe542d46247700a43a3156b924a6b6e6a07`. Este hash procede del servidor: aún no se ha contrastado contra un archivo local. La ficha declara Apache-2.0. [Modelo y configuración fijados](https://huggingface.co/HeartMuLa/HeartTranscriptor-oss/tree/ee842de9aeec454236badef2205dea47a1fd8410)

CTranslate2 admite Whisper de Transformers. En la revisión `a22ba1c63ee35d1a0d25db149aa2a66d36a6a732`, `WhisperConfig` selecciona `WhisperLoader`, sin necesitar código del repositorio del modelo. Los cuatro archivos relevantes del conversor instalado 4.9.0 coinciden byte por byte con esa revisión. [Guía oficial](https://opennmt.net/CTranslate2/guides/transformers.html#whisper) · [Cargador oficial](https://github.com/OpenNMT/CTranslate2/blob/a22ba1c63ee35d1a0d25db149aa2a66d36a6a732/python/ctranslate2/converters/transformers.py)

La API permite `TransformersConverter(load_as_float16=True)` y después `convert(quantization="int8")`. La CLI de esta versión no tiene un argumento independiente `--load_as_float16`: lo activa al escoger `int8_float16` o `float16`. Se usará la API para declarar los dos pasos explícitamente. Los pesos se redondearán primero a FP16; el cuantizador convierte cada matriz a FP32 para calcular sus escalas int8. Los parámetros que no cuantiza permanecen FP16 en disco, y el runtime CPU de Apple los expande a FP32. **No es equivalente a cuantizar directamente los pesos FP32.** [API oficial](https://opennmt.net/CTranslate2/python/ctranslate2.converters.TransformersConverter.html) · [Cuantizador](https://github.com/OpenNMT/CTranslate2/blob/a22ba1c63ee35d1a0d25db149aa2a66d36a6a732/python/ctranslate2/specs/model_spec.py) · [Tipos admitidos en CPU](https://opennmt.net/CTranslate2/quantization.html)

## Cómo evitar retener el archivo FP32 completo

Sólo activar FP16 no resuelve por sí mismo la carga. Transformers 4.57.1 inicializa el modelo en `meta`, abre el safetensors y obtiene/castea cada tensor. El lector predeterminado mantiene un mapa del archivo FP32 mientras se va formando el modelo FP16. Una estimación que retenga todas esas páginas, el destino FP16 y 512 MiB de runtime alcanza unos 4,77 GiB, antes de otros temporales. Que el sistema pueda desalojar páginas no justifica dar ese ahorro por hecho. Además, en esta versión `low_cpu_mem_usage` es una opción de compatibilidad que se ignora; no es un límite de memoria. [Carga oficial de Transformers 4.57.1](https://github.com/huggingface/transformers/blob/v4.57.1/src/transformers/modeling_utils.py)

La ruta seleccionada utiliza `safe_open(..., backend="pread")` de safetensors **0.8.0**, versión fijada y comprobada aquí. No se afirma que sea la primera versión que incorpore la función. Su implementación lee el tensor solicitado mediante lectura posicional, sin conservar el mapa completo como almacenamiento. Hay un mapeo transitorio para leer la cabecera; no se recorren los pesos durante esa lectura. `get_tensor` lee directamente a un búfer de ese tensor; `get_slice(...)[...]` puede necesitar dos búferes del tensor. [Implementación oficial](https://github.com/huggingface/safetensors/blob/v0.8.0/bindings/python/src/lib.rs)

Transformers no expone ese selector en `from_pretrained`. Falta implementar un envoltorio experimental pequeño que sustituya **sólo `transformers.modeling_utils.safe_open` durante esa llamada**, añada `backend="pread"`, exija CPU y restaure la función original en `finally`, incluso si falla la carga. No se modificarán paquetes instalados ni se cambiará el lector global de otros procesos. Los puntos de apertura relevantes están en `load_state_dict`, `_load_state_dict_into_meta_model` y la comprobación de metadatos del mismo módulo. El resto del conversor seguirá siendo oficial. Esta adaptación requiere controles de restauración, rechazo de otro dispositivo y revisión antes de cargar pesos.

El control pequeño ya realizado creó un safetensors de cuatro valores FP32. `mmap` y `pread`, con backend NumPy, devolvieron exactamente los mismos nombres, forma, tipo, valores y selección completa. **No prueba aún la ruta PyTorch/Transformers, el consumo de un checkpoint real ni la calidad de transcripción.** No se importó torch en ese control.

## Presupuesto preventivo

Todos los tamaños siguientes son MiB binarios. La arquitectura permite estimar 763.857.920 parámetros únicos; sus bytes FP32 difieren del tamaño publicado en 112.624 bytes. Es compatible con una cabecera y metadatos, pero falta verificar el inventario real de tensores. La salida int8 con parámetros restantes FP16 se estima en **733,47 MiB**, más cabeceras y tokenizer.

| Conversión seleccionada, FP16/pread → int8 | Reserva MiB |
|---|---:|
| Todos los parámetros FP16 retenidos | 1.456,94 |
| Todas las copias de Q/K/V fusionadas en FP16 | 432,42 |
| Salida int8, escalas FP32 y resto FP16 | 733,47 |
| Dos temporales FP32 de la matriz más grande | 405,20 |
| Imports y retención del asignador | 512,00 |
| Copia de serialización de la mayor matriz int8 | 50,65 |
| **Suma preventiva** | **3.590,68** |
| **Corte propuesto por RSS o huella física** | **4.096,00** |

Las copias Q/K/V no desaparecen al elegir FP16: pasan de 864,84 a 432,42 MiB. `fuse_linear` concatena matrices; la cuantización utiliza temporales FP32 por matriz y la serialización puede crear otra copia. El cálculo retiene reservas que no necesariamente coinciden en el tiempo, pero tampoco modela todo el comportamiento del asignador. Los aproximadamente 505 MiB de margen no son una cota garantizada. [Fusión oficial](https://github.com/OpenNMT/CTranslate2/blob/a22ba1c63ee35d1a0d25db149aa2a66d36a6a732/python/ctranslate2/converters/utils.py) · [Optimización y serialización](https://github.com/OpenNMT/CTranslate2/blob/a22ba1c63ee35d1a0d25db149aa2a66d36a6a732/python/ctranslate2/specs/model_spec.py)

Para inferencia se reservan dos copias del peso int8 con el resto expandido a FP32, cachés K/V duplicadas por los dos beams y capacidad conservadora de 448 tokens, dos matrices de atención del codificador, alineación, audio y runtime:

| Inferencia CPU, lote uno, beam dos | Reserva MiB |
|---|---:|
| Dos copias de pesos como reserva, sin afirmar que ambas existan | 1.477,57 |
| K/V: `2 × 24 × 2 × (1500 + 448) × 1024 × 4` bytes | 730,50 |
| Dos matrices de atención del codificador | 274,66 |
| Alineación por palabras | 128,00 |
| Audio/características hasta 300 segundos | 160,00 |
| Imports/asignador | 256,00 |
| **Suma preventiva** | **3.026,73** |

El cálculo análogo con beam cinco era 4.122,48 MiB; no ofrecía margen suficiente bajo la misma cuota. El ejemplo original Heart usa **beam dos**, de modo que se propone esa configuración declarada, sin presentarla como una comparación en la que sólo cambian los pesos. Se mantiene el corte de 4 GiB; no se amplían cuotas. Ninguna de estas sumas es un pico medido.

Se observaron **13,13 GiB libres en disco** al revisar esta nota. Fuente FP32 y salida prevista requieren unos 3,56 GiB sin dependencias, cachés ni descargas parciales. La propuesta exige volver a comprobar al menos 12 GiB antes de descargar, usar un destino explícito sin duplicación del archivo en otra caché y conservar el origen y los hashes. La disponibilidad cambia y no queda reservada por este informe.

## Vocabulario y tiempos

La unión del vocabulario y tokens añadidos contiene exactamente **51.865 identificadores consecutivos**. Se comprobaron los identificadores de inglés `50259`, español `50262`, transcripción `50359`, ausencia de voz `50362` y ausencia de timestamps `50363`. Están presentes los **1.501 tokens de tiempo**, de `50364` a `51864`, correspondientes a 0–30 segundos con pasos de 20 ms. El preprocesador declara 16 kHz, 80 mel, FFT 400 y salto 160. Se fijará el idioma de cada canción explícitamente: la configuración general incluye un prefijo inglés, aunque `generation_config.json` no fija idioma ni `forced_decoder_ids`. [Tokenizer, preprocesador y generación originales](https://huggingface.co/HeartMuLa/HeartTranscriptor-oss/tree/ee842de9aeec454236badef2205dea47a1fd8410)

Las seis cabezas de alineación son `[[13,15],[15,4],[15,15],[16,1],[20,0],[23,4]]`. Un control aislado del método oficial `WhisperLoader.set_config`, sin importar modelos, verificó que transfiere esas cabezas, idiomas y supresión. Tras convertir se volverán a comprobar en el `config.json` generado. Hay que copiar `tokenizer.json` y `preprocessor_config.json`; **no sobrescribir la configuración generada por CT2 con la de Transformers**. La carga exigirá tokenizer local para evitar una descarga de reserva. [Conversor](https://github.com/OpenNMT/CTranslate2/blob/a22ba1c63ee35d1a0d25db149aa2a66d36a6a732/python/ctranslate2/converters/transformers.py) · [Carga y alineación de faster-whisper](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py)

Conservar tokens y cabezas sólo demuestra compatibilidad estructural. No demuestra tiempos correctos. Los tiempos de palabras obtenidos mediante atención/DTW tampoco son los límites musicales de las notas.

## Plan candidato pendiente de ejecución

Se fijan Python 3.12, torch 2.8.0, safetensors 0.8.0, Transformers 4.57.1, CTranslate2 4.9.0 y faster-whisper 1.2.1. Transformers no está instalado en el entorno de la cohorte actual: se prepararía un entorno de conversión separado después de su cierre. Las versiones son una propuesta compatible con las fuentes inspeccionadas, todavía sin ensayo de integración.

La inferencia candidata conserva los parámetros explícitos del ejemplo Heart: beam dos, máximo 256 tokens nuevos, temperaturas `[0, 0.1, 0.2, 0.4]`, umbral de compresión 1,8, log-probabilidad −1 y silencio 0,4; transcripción sin condicionar al texto anterior. Añade CPU int8, dos hilos, un trabajador, lote uno, ventanas nativas de treinta segundos, VAD desactivado y tiempos por palabra. Se declara `best_of=1` en faster-whisper para que la reserva de memoria de dos beams no quede invalidada por cinco hipótesis al activar muestreo; no se afirma un equivalente exacto de ese parámetro en el ejemplo Heart. [Ejemplo fijado](https://github.com/HeartMuLa/heartlib/blob/164788308875289016d2f7ab46dba7f77a649cf8/examples/run_lyrics_transcription.py) · [Opciones y ramas de decodificación](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py)

El orden propuesto es:

1. Terminar y congelar la cohorte ASR actual. Implementar/revisar el envoltorio con controles pequeños sin modelos, fijar fuentes y protocolo, y comprobar memoria/disco vigentes.
2. Descargar sólo la revisión declarada; verificar tamaño y hash completos. Auditar nombres, formas y tipos; comprobar valores finitos antes y después de FP16, incluyendo desbordamiento, subdesbordamiento y error de redondeo. Cualquier alias esperado de pesos compartidos deberá quedar explícito, sin ignorar silenciosamente cargas incompletas.
3. Convertir en un único hijo CPU: cuota 4 GiB y plazo 900 s. Conservar etapas y métricas; validar inventario CT2, tipos, tokens, cabezas y hashes antes de dar el directorio por completo.
4. Ejecutar un único control sintético no nulo de dos segundos, sin reproducción: cuota 4 GiB y plazo 120 s. Recoger el proceso y revisar finitud, salida y recursos antes de considerar canciones.
5. Si pasa, procesar secuencialmente las cuatro voces completas: Amorfoda, 11 y 6, Mr. Fancy Pants y Northern Star. Cada canción tendrá proceso nuevo, 4 GiB y plazo 900 s; se reutilizarán los WAV mono de 16 kHz y sus hashes ya fijados por RMS-ASR. Un fallo detiene la tanda, conserva evidencia y no eleva límites ni reintenta automáticamente.
6. Congelar las cuatro predicciones crudas y transportadas antes de abrir referencias. Comparar con el brazo Turbo `vocals/native`, una vez congelado, sin escoger por canción el brazo de RMS más favorable. Reportar WER, omisiones, inserciones, repeticiones, cobertura y errores temporales; mantener 40 como denominador, con 36 ausencias fuera del piloto.

La supervisión propuesta muestrea RSS y huella física cada 50 ms y termina/recolecta al superar cuota o plazo. No garantiza capturar un pico entre muestras. Se mantiene un solo modelo a la vez y no se utilizará MPS. El límite de 900 segundos es un techo, no una predicción de duración; todavía no existe un factor de tiempo real medido para esta cadena.

El candidato cambia pesos, FP16/int8, runtime, frontend y parámetros de decodificación frente a Turbo. También difiere del pipeline Transformers original en el recorrido de ventanas y la alineación. Se propondrá semilla 113, pero la cohorte histórica no fijó la misma semilla: si se activa muestreo, no se afirmará igualdad de azar. El ensayo podrá comparar dos cadenas completas, no atribuir cada diferencia a HeartTranscriptor por separado.

## Evidencia conservada

Los archivos pequeños, URLs y hashes están en `build/generation-next/heart-cpu-research/`. La propuesta elegida es `execution-proposal-fp16-pread-v2.json`, SHA-256 **`d8e8951e071720bb741d6f19aeb0aeb59fb666f588041a8aa3367780cb013d15`**. Su estado es `ready_to_execute=false`: falta implementar y revisar el envoltorio y coordinar el turno de modelos.

El presupuesto de esa variante está en `fp16-pread-budget.json`, SHA-256 **`e0a29ca16e082933ee64e240c7e98608244d6ebf99dcd97fad176b12e965410e`**. El control pequeño está en `safetensors-small-control.json`, SHA-256 **`ff6b4804a7e2a305d10894920f9d3131bf7e8352f47ef8a93a0b6e1f1f238ed5`**. `budget-and-token-controls.json` e `installed-source-check.json` contienen las comprobaciones estructurales. Los cálculos previos de conversión directa FP32 y beam cinco quedan como historial, no como otra tanda autorizada ni como cuotas adoptadas.
