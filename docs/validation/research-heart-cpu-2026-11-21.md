# HeartTranscriptor en CPU: conversión y presupuesto previo

Fecha: 21 de noviembre de 2026. Continuación de [la investigación de reconocedores para canto](research-letras-siguientes-2026-11-21.md). **La conversión FP16/pread → CT2 int8 está completada y congelada en este Mac, después de corregir un error del validador.** La candidata de reconocimiento usa CPU, lote uno, dos hilos y beam dos; su ejecución y calidad se documentan en [el ensayo ASR separado](research-heart-asr-2026-11-21.md). El presupuesto preventivo y las mediciones posteriores se distinguen abajo; ninguno garantiza estabilidad en cualquier uso.

La investigación inicial sólo leyó fuentes y metadatos pequeños, comparó código instalado e hizo un control de cuatro valores sintéticos con NumPy. Después se preparó un entorno independiente, se descargó el checkpoint fijado verificando sus bytes y pasó el control PyTorch diminuto. El intento completo y la corrección posterior de su validador se documentan al final. No se han abierto referencias de letras durante este trabajo. El Mac permanece silenciado.

## Compatibilidad de arquitectura y formato

El checkpoint oficial `HeartMuLa/HeartTranscriptor-oss`, revisión `ee842de9aeec454236badef2205dea47a1fd8410`, declara `WhisperForConditionalGeneration`: 24 capas de codificador, 24 de decodificador, dimensión 1.024, 16 cabezas y 80 bandas mel. Publica un archivo FP32 de 3.055.544.304 bytes, con SHA-256 LFS `9e09145b687c26330da96ad2d7ca1fe542d46247700a43a3156b924a6b6e6a07`. La descarga y el conversor posteriores contrastaron el tamaño y hash locales con esos valores. La ficha declara Apache-2.0. [Modelo y configuración fijados](https://huggingface.co/HeartMuLa/HeartTranscriptor-oss/tree/ee842de9aeec454236badef2205dea47a1fd8410)

CTranslate2 admite Whisper de Transformers. En la revisión `a22ba1c63ee35d1a0d25db149aa2a66d36a6a732`, `WhisperConfig` selecciona `WhisperLoader`, sin necesitar código del repositorio del modelo. Los cuatro archivos relevantes del conversor instalado 4.9.0 coinciden byte por byte con esa revisión. [Guía oficial](https://opennmt.net/CTranslate2/guides/transformers.html#whisper) · [Cargador oficial](https://github.com/OpenNMT/CTranslate2/blob/a22ba1c63ee35d1a0d25db149aa2a66d36a6a732/python/ctranslate2/converters/transformers.py)

La API permite `TransformersConverter(load_as_float16=True)` y después `convert(quantization="int8")`. La CLI de esta versión no tiene un argumento independiente `--load_as_float16`: lo activa al escoger `int8_float16` o `float16`. Se usará la API para declarar los dos pasos explícitamente. Los pesos se redondearán primero a FP16; el cuantizador convierte cada matriz a FP32 para calcular sus escalas int8. Los parámetros que no cuantiza permanecen FP16 en disco, y el runtime CPU de Apple los expande a FP32. **No es equivalente a cuantizar directamente los pesos FP32.** [API oficial](https://opennmt.net/CTranslate2/python/ctranslate2.converters.TransformersConverter.html) · [Cuantizador](https://github.com/OpenNMT/CTranslate2/blob/a22ba1c63ee35d1a0d25db149aa2a66d36a6a732/python/ctranslate2/specs/model_spec.py) · [Tipos admitidos en CPU](https://opennmt.net/CTranslate2/quantization.html)

## Cómo evitar retener el archivo FP32 completo

Sólo activar FP16 no resuelve por sí mismo la carga. Transformers 4.57.1 inicializa el modelo en `meta`, abre el safetensors y obtiene/castea cada tensor. El lector predeterminado mantiene un mapa del archivo FP32 mientras se va formando el modelo FP16. Una estimación que retenga todas esas páginas, el destino FP16 y 512 MiB de runtime alcanza unos 4,77 GiB, antes de otros temporales. Que el sistema pueda desalojar páginas no justifica dar ese ahorro por hecho. Además, en esta versión `low_cpu_mem_usage` es una opción de compatibilidad que se ignora; no es un límite de memoria. [Carga oficial de Transformers 4.57.1](https://github.com/huggingface/transformers/blob/v4.57.1/src/transformers/modeling_utils.py)

La ruta seleccionada utiliza `safe_open(..., backend="pread")` de safetensors **0.8.0**, versión fijada y comprobada aquí. No se afirma que sea la primera versión que incorpore la función. Su implementación lee el tensor solicitado mediante lectura posicional, sin conservar el mapa completo como almacenamiento. Hay un mapeo transitorio para leer la cabecera; no se recorren los pesos durante esa lectura. `get_tensor` lee directamente a un búfer de ese tensor; `get_slice(...)[...]` puede necesitar dos búferes del tensor. [Implementación oficial](https://github.com/huggingface/safetensors/blob/v0.8.0/bindings/python/src/lib.rs)

Transformers no expone ese selector en `from_pretrained`. El envoltorio experimental preparado sustituye **sólo `transformers.modeling_utils.safe_open` durante esa llamada**, añade `backend="pread"`, exige CPU y restaura la función original en `finally`, incluso si falla la carga. No modifica paquetes instalados ni cambia el lector global de otros procesos. Los puntos de apertura relevantes están en `load_state_dict`, `_load_state_dict_into_meta_model` y la comprobación de metadatos del mismo módulo. El resto del conversor sigue siendo oficial. Los controles de restauración y rechazo de otro dispositivo pasan, incluido el recorrido real PyTorch/Transformers con el modelo diminuto descrito abajo.

El primer control pequeño creó un safetensors de cuatro valores FP32. `mmap` y `pread`, con backend NumPy, devolvieron exactamente los mismos nombres, forma, tipo, valores y selección completa. **Ese control por sí solo no prueba la ruta PyTorch/Transformers, el consumo de un checkpoint real ni la calidad de transcripción.** No se importó torch en él; los ensayos posteriores se distinguen al final.

## Presupuesto preventivo

Todos los tamaños siguientes son MiB binarios. La arquitectura permitió estimar 763.857.920 parámetros únicos; sus bytes FP32 difieren del tamaño publicado en 112.624 bytes. La comprobación posterior de la cabecera confirmó ese número y la cobertura completa de los bytes de tensores. La previsión de salida int8 con parámetros restantes FP16 era **733,47 MiB**, más cabeceras y tokenizer; estos cálculos precedieron a la ejecución.

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

Se fijan Python 3.12, torch 2.8.0, safetensors 0.8.0, Transformers 4.57.1, CTranslate2 4.9.0 y faster-whisper 1.2.1. Tras terminar la cohorte RMS se preparó un entorno independiente en `build/generation-next/heart-transcriptor/env`, sin cambiar el de esa cohorte. Sus 35 paquetes incluyen tokenizers 0.22.2 y huggingface-hub 0.36.2, compatibles con las restricciones de Transformers. `requirements-lock.txt`, SHA-256 `880cca28f091287ee8b96ff83823649416c824329d3b51e3fd65fae2ca92fbb5`, fija las versiones efectivas. La carga y conversión se comprobaron después; el reconocimiento sigue pendiente.

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

Los archivos pequeños, URLs y hashes están en `build/generation-next/heart-cpu-research/`. La propuesta de investigación seleccionada fue `execution-proposal-fp16-pread-v2.json`, SHA-256 **`d8e8951e071720bb741d6f19aeb0aeb59fb666f588041a8aa3367780cb013d15`**. Conserva su estado histórico `ready_to_execute=false`; el plan del adaptador preparado posteriormente se identifica abajo.

El presupuesto de esa variante está en `fp16-pread-budget.json`, SHA-256 **`e0a29ca16e082933ee64e240c7e98608244d6ebf99dcd97fad176b12e965410e`**. El control pequeño está en `safetensors-small-control.json`, SHA-256 **`ff6b4804a7e2a305d10894920f9d3131bf7e8352f47ef8a93a0b6e1f1f238ed5`**. `budget-and-token-controls.json` e `installed-source-check.json` contienen las comprobaciones estructurales. Los cálculos previos de conversión directa FP32 y beam cinco quedan como historial, no como otra tanda autorizada ni como cuotas adoptadas.

## Adaptador preparado después de la investigación

`scripts/experiments/heart_conversion.py` implementa únicamente planificación y conversión supervisada; no descarga pesos ni transcribe. Su envoltorio conserva los demás argumentos, exige CPU/pread y restaura el lector en éxito o error. La auditoría del cast lee como máximo 4 MiB FP32 por bloque y sólo conserva hashes y estadísticas escalares; no acumula matrices ni usa temporales FP64. El supervisor existente aplica 4 GiB y 900 segundos, recoge el trabajador y exige éxito antes de congelar el resultado.

Antes del arranque se exige el archivo local oficial con tamaño/hash correctos. Después se comprueban carga, vocabulario, cabezas, inventario binario CT2, finitud, escalas y aliases. La configuración generada no se sobrescribe. Los archivos terminados quedan en `conversion/ct2-model`; un `frozen.json` nuevo enlaza plan, recursos y manifiesto sólo después de confirmar la salida del proceso.

La nueva planificación enlaza la tanda RMS **v3 terminada**, plan `0a9e4d81a2462977c8b21871f9cc3fe5451db48ead5d6cb853d2e902e6bf183c` y freeze `c88bf5aa82893d41a018a88e65f03db8bd6182a092da3f51df79f9f17a253e12`. La referencia a v2 en la propuesta de investigación anterior queda como historial y no se reutiliza para la ejecución. Se admiten un entorno independiente u overlay explícito; ambos recorridos del controlador se han comprobado con un trabajador simulado.

La versión inicial pasó **25 controles unitarios**, sin importar torch, Transformers, CTranslate2 ni safetensors. También se verificaron los 35 paquetes y cinco fuentes instaladas mediante metadatos y hashes, sin importar esos runtimes. Un control adicional del safetensors real en el entorno independiente leyó cuatro valores mediante el envoltorio NumPy/pread y comprobó su restauración; está en `build/generation-next/heart-transcriptor/reader-control.json`. Estas pruebas no convierten ni cargan modelos. Dos revisiones estáticas independientes no encontraron defectos concretos en wrapper/recursos/auditoría ni en fuente/salida/freeze; ese resultado no demostraba estabilidad o corrección con pesos reales y no detectó el error de nombres descrito después.

El mínimo de disco del conversor es **4 GiB libres después de disponer del origen**. Los 12 GiB de la propuesta anterior correspondían al momento anterior a la descarga; exigirlos también después de guardarla contaría dos veces esa reserva.

El primer plan ejecutable está en `build/generation-next/heart-transcriptor/conversion-v1/plan.json`, SHA-256 **`924eb47cb1a67b96735df5ed99369a578c345be3d354453126ced43bb0cd8c1e`**; fija el adaptador `f2ac6016db8dd7875fb88cdd917eea74b95cd8e2f84a3579b97ef82c719f0cec`. La descarga separada quedó registrada en `source-download.json`: trece archivos de la revisión, incluido el peso de 3.055.544.304 bytes con el SHA oficial, sin carga de modelos durante la descarga.

Antes de la conversión completa pasó **un único control real diminuto**: `tiny-whisper-control.py`, SHA `c92854a297543bf05d71d9ee913cea5f49737de0d7d875d10cbda381c771bfab`, con plan `tiny-control-plan.json`, SHA `0daa2a1b4cc9d9b6f4fac885f54d39c4088ee0a21af9a51a1ec7ccd526ee4eaf`. Creó un Whisper aleatorio de dimensión 16 y una capa por lado, guardado localmente en **50.160 bytes**. Las **51 entradas del estado** coincidieron exactamente con el cast FP16 esperado; las cuatro lecturas reales de Transformers usaron CPU/pread y el lector original quedó restaurado. No hizo reconocimiento ni leyó el checkpoint grande.

El trabajador PID 15553 salió con código **0**, quedó recogido y tardó **15,419 segundos**. Con cuota de **1,5 GiB y 60 segundos**, sus máximos muestreados fueron **337,000 MiB RSS** y **265,516 MiB de huella física**, en 292 muestras, sin señales de terminación. `tiny-control-v1/frozen.json`, SHA **`1ed77c173fb501572b69bda89c3458b55c5a9343f8a94fe7501d147fa6906b45`**, enlaza plan, recursos y comparación. Es una comprobación real de la API y del cast pequeño en el Mac; no mide el pico de Heart completo, su cuantización int8 ni la fiabilidad de las letras.

## Primer intento completo y corrección del validador

La ejecución de `conversion-v1` completó lectura, carga FP16 y conversión int8, y llegó a la fase `after_conversion`. A continuación el validador confundió `encoder/layer_norm` con una capa numerada y llamó a `int("norm")`. El trabajador **PID 15596 salió con código 2**, quedó recogido y no recibió señales: no fue un corte de memoria. Tardó **10,886 segundos**, con máximos muestreados de **2.707,203 MiB RSS** y **2.867,597 MiB de huella física**, en 205 muestras, bajo la cuota de 4 GiB. Este resultado no se presenta como ejecución exitosa.

Se conservan íntegros los quince archivos de v1, incluyendo `ct2-staging`; no se renombraron ni se escribió un freeze aceptado. El adaptador original `f2ac6016…` se copió a `validation-v2/heart_conversion-f2ac6016.py` antes de editarlo. La corrección `e99bd6f7529c739b12e34be6f197815674091b62f6d32694242f175d1d02ffff` cambia únicamente el reconocimiento de `layer_` por el patrón de capa numérica `layer_([0-9]+)/`. Una regresión reprodujo primero `int("norm")`; después pasó, conservando el rechazo cuando falta la capa 23. El conjunto completo pasa **26 controles**, sin modelos.

Se validaron los bytes ya generados sin repetir la conversión: **1.057 variables, un alias, 51.865 tokens y seis cabezas** pasan todos los controles de salida. El mismo inventario reproduce el error con la expresión antigua. Los hashes de los quince archivos v1 coincidieron antes y después; no se importaron torch, Transformers, CTranslate2 ni safetensors. La evidencia es `validation-v2/review.json`, SHA **`55de776eb81fa038adda04ecfecd60b080a5f4a67d1d0680f766133eb66d6d60`**, y `validation-v2/validation.json`, SHA **`12571a5b490baf1299a2ab14f3f62422cc3ed6b0e1430fd39d4c355d1065a91e`**.

La revisión independiente confirmó que el cambio productivo se limita al parser numérico, contrastó las 24 capas de cada lado separando componentes por otro procedimiento y reconcilió las 1.057 variables, el alias y los quince hashes originales. Está en `validation-v2/independent-review.json`, SHA **`2ac7680d90b4fdf2e47b095dd72656cc5815af4c945f46b0fdfcbdf2215d8eb8`**; no repitió el modelo ni el validador completo.

La validación posterior acredita los archivos inspeccionados, **no cambia la salida 2 del trabajador ni crea un éxito retroactivo**. La ejecución corregida siguiente utilizó un plan nuevo y mantuvo ese primer intento intacto.

## Conversión v2 terminada y congelada

La única repetición completa con el validador corregido se declaró en `conversion-v2/plan.json`, SHA **`fa8da5c74619ea484c4e4d970414a59a428cf166d918a774744a71998160e35c`**. El trabajador **PID 16021 salió con código 0 y quedó recogido**, sin señales ni motivo de corte. Tardó **12,072 segundos**; las 228 muestras registraron máximos de **2.936,891 MiB RSS** y **2.873,675 MiB de huella física**, bajo los mismos 4 GiB. Son medidas de esa conversión CPU en el Mac real, no del reconocimiento de una canción ni picos absolutos entre muestras.

El freeze aceptado es `conversion-v2/frozen.json`, SHA **`c9827e4989869d5a870b6b8a4bdac23914e680fcaed59936f0e7150ea33a2d41`**. Sus cinco archivos CT2, incluido `model.bin` de **769.156.493 bytes**, son idénticos por SHA-256 a los que produjo v1. El hash del binario es **`1c207f1693c4544e83536992b3b72c9d7098f99f0a6966fa054bbfb090bf0c3d`**. La corrección resolvió la aceptación del inventario; no cambió esos bytes ni permite afirmar equivalencia numérica con el checkpoint FP32.

Una revisión posterior leyó los archivos mediante hashes en streaming, verificó los trece archivos del manifiesto del trabajador, los enlaces del freeze y la igualdad de los cinco archivos CT2; volvió a comprobar que los quince archivos v1 seguían intactos. También contrastó recursos, inventario, vocabulario y cabezas, y comprobó con `ps` la ausencia de PID 16021. Está en `validation-v2/conversion-v2-review.json`, SHA **`d761088f9946d69812c07c60529ee2235859ca0693ff95f678941e8f856642fc`**. No repitió conversión ni cargó modelos.

El resultado acredita un artefacto convertido y validado estructuralmente. Por sí solo no mide WER, sincronización de palabras ni calidad musical. El [ensayo ASR posterior](research-heart-asr-2026-11-21.md) conserva por separado su control sintético, plan de canciones y evaluación.
