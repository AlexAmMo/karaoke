# Recursos de Turbo CPU: presupuesto antes del segundo control

La propuesta es **un único control sintético adicional con 4 GiB y 120 s**, CPU int8, el mismo modelo y las mismas opciones. La cuota se apoya en los tamaños reales de los tensores, la ruta de conversión y un margen explícito; no es una garantía de que la carga o una canción completa termine. Se conserva el intento de 2 GiB, no se prevén nuevas subidas si este control falla y todavía no se autoriza por ello la tanda de dieciséis transcripciones. Este informe registra investigación estática y un control de imports, **no una medición de carga a 4 GiB**. El experimento de letras está descrito en [research-letras-rms-asr-2026-11-21.md](research-letras-rms-asr-2026-11-21.md).

## Qué se ha medido

El control anterior terminó en 1,726 s, al observar 2.149,23 MiB RSS y 2.122,52 MiB de huella física. El marcador anterior a importar/construir `WhisperModel` existe y el posterior no. No llegó a transcribir. El supervisor envió `SIGKILL`, recogió el proceso y confirmó después la ausencia de su PID. Su evaluación y recursos permanecen en `build/generation-next/rms-vad-asr/v1/`; no se reescribieron.

Para separar importación y carga se ejecutó **una sola prueba sin construir modelos ni abrir `model.bin`**, bajo 512 MiB/30 s. Importó CTranslate2 4.9.0 y `WhisperModel` de faster-whisper 1.2.1, sin instanciar la clase. Terminó en 0,307 s: imports CT2 a los 0,015 s, faster-whisper a los 0,094 s. Las seis muestras registraron máximo de **56,31 MiB RSS** y **30,91 MiB de huella**. Salida cero, PID 11280 recogido y ausente después. Esto sitúa el gran salto en la fase posterior a esos imports; no identifica cada asignación interna.

Script, comando, versiones, fases y recursos están congelados en `build/generation-next/rms-vad-asr/resource-review-v1/import-only/`, SHA-256 de `frozen.json`: `4b861b6726692d25cd26b9f23e2eee93bd178e747d200a37ee2d16e7e455e270`. No se cargó otro modelo durante esta investigación y el Mac permaneció silenciado.

## Ruta de carga comprobada

Se fijó el código de CTranslate2 4.9.0 a la revisión `a22ba1c63ee35d1a0d25db149aa2a66d36a6a732`. Su [cargador](https://github.com/OpenNMT/CTranslate2/blob/a22ba1c63ee35d1a0d25db149aa2a66d36a6a732/src/models/model.cc) lee las variables completas antes de ajustar el tipo de cómputo. Al convertir una matriz FP16 a int8 crea un temporal FP32 y el destino cuantizado, además de escalas. La conversión procede matriz a matriz: no se presupone una copia FP32 de todo el modelo. La [operación CPU de cuantización](https://github.com/OpenNMT/CTranslate2/blob/a22ba1c63ee35d1a0d25db149aa2a66d36a6a732/src/ops/quantize_cpu.cc) aplica el máximo absoluto por fila. No se sustituyó esa operación ni se requantizaron los pesos en este análisis.

La [documentación de cuantización](https://opennmt.net/CTranslate2/quantization.html) confirma que `compute_type` puede convertir al cargar y que ARM64/Apple CPU usa int8 con componentes flotantes FP32. Por tanto, el archivo FP16 y el destino int8 tienen tamaños distintos y pueden coexistir transitoriamente. El [lector de archivos](https://github.com/OpenNMT/CTranslate2/blob/a22ba1c63ee35d1a0d25db149aa2a66d36a6a732/src/models/model_reader.cc) usa un flujo de disco; el adaptador ya pasa una carpeta, no un diccionario con el archivo entero en bytes.

La [implementación de faster-whisper 1.2.1](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py) pasa esa ruta a CTranslate2, con `num_workers=1` por defecto. Nuestro caso usa ese único trabajador, tres hilos CPU, `files=None` y audio previamente preparado. No se encontró una segunda instancia Python de Turbo ni una copia Python innecesaria de su archivo que pueda eliminarse sin cambiar el ensayo.

## Inventario del archivo real y estimación

El archivo local verificado por el plan tiene 1.617.884.929 bytes, SHA-256 `e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da`. Se leyeron sólo **26.354 bytes de cabeceras** y se saltaron todos los datos de los tensores; después se consultaron cuatro bytes de atributos enteros de número de cabezas. No se crearon tensores ni se ejecutó inferencia. `read_tensor_metadata.py`, `model-metadata-only.json` y `architecture-attributes-only.json` conservan el procedimiento y los resultados, bajo `resource-review-v1/`.

El formato es v6, `WhisperSpec` revisión 3, con 486 variables. Los datos FP16 suman 1.617.858.560 bytes; otros quince bytes son atributos enteros. El embedding mayor es `[51866,1280]`. Las formas y atributos confirman 32 capas de encoder, cuatro de decoder, dimensión 1.280, veinte cabezas y contextos de 1.500 posiciones acústicas/448 tokens. La proyección de salida comparte el embedding: no se cuenta una copia independiente que no está en el archivo.

| Componente del presupuesto conservador | MiB |
|---|---:|
| Datos FP16 de origen, sin asumir devolución inmediata de páginas | 1.542,91 |
| Destino de pesos int8 | 768,47 |
| Otros flotantes FP32 y escalas | 13,81 |
| Temporal FP32 de la matriz mayor | 253,25 |
| RSS de imports observado | 56,31 |
| Estimación de KV con cuatro capas, beam cinco y contextos máximos | 380,47 |
| Reserva de dos matrices de atención, 20×1500×1500 float32 | 343,32 |
| Reserva de audio/rasgos para la entrada nativa de hasta 300 s | 160,00 |
| **Suma orientativa** | **3.518,55** |
| **Cuota propuesta** | **4.096,00** |
| **Margen sobre esa suma** | **577,45** |

La suma incluye deliberadamente fases que no tienen por qué coexistir y conserva el origen completo como precaución ante páginas retenidas. **No es una cota matemática del asignador**: no prueba que incluya todos los espacios de trabajo internos. La [atención de CT2](https://github.com/OpenNMT/CTranslate2/blob/a22ba1c63ee35d1a0d25db149aa2a66d36a6a732/src/layers/attention.cc) construye puntuaciones y cachés; la reserva expresa las formas del modelo y el beam ya fijado, sin cambiar precisión, ventanas ni tokens. Los cálculos exactos, unidades y esta limitación están en `budget.json`. El límite de 4 GiB es una cuota experimental de parada, nunca una promesa de consumo máximo.

La instantánea `system-before-proposed-control.json` registra 16 GiB físicos, aproximadamente 2,03 GiB wired, 1,69 GiB libres y 5,46 GiB inactivos. El indicador del sistema comunica 83 % libre; el swap utilizado era 1.074,69 MiB. Estas categorías no se suman indiscriminadamente ni se convierten en una reserva. Junto con ejecutar sólo un proceso de modelos, apoyan ensayar la cuota de 4 GiB; se debe volver a comprobar el estado al lanzarlo.

## Opciones que no se aplican a este control

- El [asignador CPU](https://github.com/OpenNMT/CTranslate2/blob/a22ba1c63ee35d1a0d25db149aa2a66d36a6a732/src/cpu/allocator.cc) usa asignación alineada/liberación ordinaria fuera de MKL. No se ha identificado una opción documentada de caché CPU equivalente a las arenas de ONNX que deba desactivarse.
- [`CT2_PACKED_GEMM`](https://opennmt.net/CTranslate2/environment_variables.html) pertenece a Intel MKL; el [selector de backend](https://github.com/OpenNMT/CTranslate2/blob/a22ba1c63ee35d1a0d25db149aa2a66d36a6a732/src/cpu/backend.cc) no lo aplica al backend int8 Ruy de ARM. No se propone ese ajuste como arreglo del M4. La opción documentada de mmap corresponde a Drama3, no a Whisper.
- Guardar otra representación precuantizada podría evitar conversiones futuras, pero exige generar y comprobar un artefacto distinto y su equivalencia numérica. No se da por idéntico sin probarlo y no se hace aquí. Tampoco se descarga un modelo int8 de terceros, cambia `compute_type`, reduce beam o sustituye Turbo.
- Los tiempos históricos de Turbo en `build/generation-v2/evaluate.log` —aproximadamente 66–96 s— no incluyen un pico de memoria atribuible al trabajador. El benchmark pequeño de 16–17 s era Small. No se usa ninguno como prueba de memoria de Turbo.

Se mantiene el monitor firmado `5cc80cefe57a4088701dc3ea1e9bfa2be3ee5120754c4d6a702ccf184ed3ef97`, muestreo de RSS/huella cada 50 ms, muerte inmediata al exceder cuota o perder telemetría, y cierre confirmado. El supervisor `yourmt3_notes.py` permanece en `0a36facfe0b49da79a4b8ac24c79bce2fa34f28854891d45f13890ffb9d84cc8`; no se modificó. El nuevo plan debe declarar 4 GiB/120 s antes de cargar, conservar v1 y separar importación/carga/inferencia en sus marcas. Si el control termina, seguirá sin medir la calidad de letras ni demostrar el pico de una canción completa.

Las fuentes pequeñas están guardadas con URL y SHA-256 en `resource-review-v1/sources/manifest-extended.json`. No se descargaron pesos ni se modificó el generador público.

## Revisión previa del plan v2

Se revisó sin modelos `rms-vad-asr/v2/plan.json`, SHA-256 `c3c3cb8b1b97c80ebbf43c768ac0a642813098c21af25ecfa6495330931f346e`: los 4.294.967.296 bytes y 120 s del control llegan desde el plan a `run_bounded`. La ejecución del corpus es otra acción y no se inicia automáticamente. Se comprobaron los ocho WAV reales contra v1, igualdad de archivos del modelo, IDs y opciones de decodificación, hashes del adaptador/monitor y evidencias enlazadas. La nueva marca `after-import.json` separa importación y constructor. No se ejecutó el modelo durante esta revisión ni se repitió la suite del adaptador. `review-rms-v2.json` conserva el alcance, SHA-256 `4f391484d8af85194236b33eb93a62d402a9cd82a0b1f2fd636126bb8a7d2dc0`. El resultado posterior del control pertenece al informe del ensayo RMS-ASR, no a esta estimación previa.
