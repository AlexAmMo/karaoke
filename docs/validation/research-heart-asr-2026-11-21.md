# Heart ASR: adaptador preparado, sin inferencia

Está implementado `scripts/experiments/heart_asr.py` para comparar una cadena Heart fija con las cuatro salidas Turbo `vocals-native` ya congeladas de RMS v3. **No se han cargado modelos ni ejecutado el control o las canciones con este adaptador.** El plan real exige primero una conversión Heart terminada, validada y congelada por `heart_conversion.py`; no se crea un plan ejecutable con pesos pendientes.

La propuesta previa `build/generation-next/heart-cpu-research/execution-proposal-fp16-pread-v2.json`, SHA-256 `d8e8951e071720bb741d6f19aeb0aeb59fb666f588041a8aa3367780cb013d15`, fija la variante: origen oficial HeartTranscriptor, conversión FP32 → FP16 mediante lectura pread → CTranslate2 int8, CPU, dos hilos, un trabajador y una canción a la vez. La conversión puede cambiar valores respecto de cuantizar directamente FP32. La comparación posterior será entre cadenas completas —pesos, conversión, opciones y ejecución—, no una prueba aislada de los pesos ni equivalencia con la implementación del autor.

## Condiciones fijas y reloj

Se reutilizan, sin recodificar, las cuatro ondas vocales mono de 16 kHz de RMS: Amorfoda, 11 y 6, Mr. Fancy Pants y Northern Star. El plan verifica sus hashes, número de muestras, canales, frecuencia, valores finitos y señal no nula. Conserva el enlace al máster original y a la voz separada. La referencia de comparación es exclusivamente Turbo `vocals-native`; no se selecciona un brazo RMS por canción. La propuesta histórica conserva enlaces antiguos a v2, pero el plan nuevo exige expresamente RMS **v3**, su freeze completo y las cuatro predicciones vocales correspondientes.

Heart recibe cada canción completa con segmentación nativa de 30 s, `beam_size=2`, `best_of=1`, temperaturas `[0, 0.1, 0.2, 0.4]`, umbral de compresión 1,8, log-probabilidad −1, ausencia de voz 0,4 y máximo de 256 tokens nuevos. Usa tiempos de palabra, VAD desactivado, texto previo desactivado e idioma fijo es/en. La semilla de CTranslate2 es 113. El Turbo histórico no había fijado una semilla; no se afirma que los caminos de muestreo sean equivalentes si se activa la temperatura de respaldo.

Se reutiliza `generation_worker.transcribe` para el remuestreo y los filtros de palabra del producto. Un envoltorio valida su llamada y sustituye **todos los argumentos de decodificación** por los de Heart: el `beam_size=5` interno de producción no llega al reconocedor. Registra argumentos recibidos y efectivos, y copia los segmentos crudos antes de filtrar. Conserva signos, repeticiones, palabras de duración no positiva y cruces de frontera en la vista cruda; las líneas filtradas se guardan aparte. El control simulado confirma que la onda preparada llega idéntica y que el reloj absoluto no cambia.

El plan fija la fuente de producción actual, que ya incorpora la guardia de silencio posterior a RMS. Las cuatro ondas y el control Heart son no nulos; no se modifica la fuente congelada ni se vuelve a ejecutar Turbo v3. Los tiempos ASR que se obtengan no se presentarán como una alineación forzada final ni como finales correctos de notas musicales.

## Procedencia y supervisión

El plan firma propuesta, adaptador, ayudantes RMS, función de producción, supervisor, monitor, conversión, modelo convertido, entradas y baseline. El consumidor de la conversión comprueba su plan, salida exitosa, recogida, manifiesto del trabajador y hashes de los archivos convertidos, sin cargar tensores. El modelo usa archivos locales y modo offline. Las versiones fijadas de inferencia son faster-whisper 1.2.1, CTranslate2 4.9.0, NumPy 2.5.5, SciPy 1.18.1 y SoundFile 0.14.0.

El comando `synthetic` crea dos segundos de señal finita no nula: seno de 440 Hz con armónico de 880 Hz y envolvente suave, mono a 16 kHz. No se reproduce por altavoces. Tiene cuota de **4 GiB** y plazo de **120 s**, y sólo comprueba carga, opciones, captura y serialización. Una letra reconocida en esa señal no demostraría precisión de canto. Sólo una salida exitosa y recogida produce `synthetic-frozen.json`.

El comando `execute` exige ese control del mismo plan. Después inicia cuatro procesos frescos y secuenciales, cada uno con **4 GiB y 900 s**. El supervisor muestrea RSS y huella física cada 50 ms; mata y recoge ante superación, pérdida de telemetría, plazo o interrupción. El controlador detiene la cohorte al primer fallo, conserva archivos parciales y no reintenta ni aumenta cuota. `frozen.json` sólo aparece tras las cuatro salidas correctas y recogidas. Los límites son supervisión por muestras, no topes de asignación impuestos por el sistema.

No hay una estimación medida de duración Heart. Los cuatro plazos suman 60 minutos, más el control de 120 s; son máximos de supervisión, no un tiempo esperado. La carga real y el máximo de memoria siguen pendientes del control coordinado con el único proceso de modelos del Mac.

## Controles sin modelos y contrato de evaluación

El `selftest` pasó nueve controles ligeros en `build/generation-bench/env`: señal sintética no nula, reloj exacto, opciones Heart efectivas, filtros productivos y repeticiones, dataclasses anidadas y escalares NumPy, indicadores de frontera, rechazo de NaN/infinito/objetos arbitrarios, rechazo de cambios en la llamada de producción y ausencia de imports de Torch/faster-whisper/CTranslate2. La serialización conserva precisión y campos, exige `allow_nan=False` y valida todo antes de crear el archivo inmutable.

En `tests/test_heart_asr.py` pasan nueve pruebas adicionales de enlace de conversión, alteraciones de evidencia, propagación de cuota/plazo, rechazo de reintentos, parada al primer fallo y ausencia de freeze sin recogida. El décimo caso invoca el mismo control de audio: se omite en el entorno básico de la app porque no instala SciPy, y **sí se ejecutó correctamente** mediante el `selftest` en el entorno de investigación. Ruff y `git diff --check` pasan. No se cambió producción.

El contrato acordado con `heart_asr_evaluate.py` usa `heart-native` frente a `turbo-vocals-native`, sin elegir por canción. Cada predicción contiene identidad, hash de plan, audio, `raw_words`, `product_lines` e intervalos del reloj original. La congelación final conserva predicción, recursos y todos los archivos parciales por canción. El evaluador separado exige los cuatro candidatos completos, valida globalmente la procedencia antes de leer referencias y conserva 40 identidades por brazo: 80 condiciones y 160 filas al separar vistas cruda/productiva. No se ha creado aún el protocolo real, porque necesita el plan que enlazará la conversión terminada.

```sh
# Ejecutado: control ligero, sin cargar un modelo.
build/generation-bench/env/bin/python scripts/experiments/heart_asr.py selftest
uv run pytest -q tests/test_heart_asr.py

# Posterior a conversión congelada y revisión, todavía no ejecutado:
build/generation-bench/env/bin/python scripts/experiments/heart_asr.py plan \
  --conversion-freeze /ruta/a/conversion/frozen.json \
  --output build/generation-next/heart-asr/v1

# Comandos separados; requieren coordinación del único proceso de modelos.
# ... heart_asr.py synthetic --output build/generation-next/heart-asr/v1
# ... heart_asr.py execute --output build/generation-next/heart-asr/v1
```
