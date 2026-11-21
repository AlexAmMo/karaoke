# Generación fiable de nuevas canciones: 21 de noviembre de 2026

No está demostrada una generación de letra y mapa casi perfecta para cualquier canción. Esta continuación de 0.3.1 investiga alternativas reutilizables y las compara antes de incorporarlas al producto. Las configuraciones ensayadas de SwiftF0, del detector fonético PPG y de la reconstrucción experimental de SingMelody no justifican sustituir el motor actual: ninguna consigue aprobar los mapas completos. Qwen3-ASR empeora la letra en treinta de las cuarenta grabaciones.

## Criterio y método

Se mantienen las mismas 40 grabaciones completas: veinte españolas de YouTube y veinte inglesas con licencia abierta, identificadas en [el manifiesto](generacion-muestra.json). Los candidatos reciben audio y, cuando corresponde, predicciones previas; no reciben el mapa humano reservado para evaluación. La base sí puede incorporar letras corroboradas de otras fuentes, como subtítulos manuales. Los mapas se congelan con SHA-256 antes de medirlos; las referencias corresponden al mismo máster. No se desplaza el reloj, transpone la referencia, recorta la canción ni elimina una canción fallida del denominador.

Estas cuarenta grabaciones ya han guiado decisiones de desarrollo: constituyen un conjunto de regresión, **no una evaluación inédita**. Si un candidato mejora lo suficiente, todavía necesitará comprobarse en nuevas grabaciones antes de atribuirle fiabilidad general.

La comparación con la base identifica el mismo máster, pero no permite aislar siempre el efecto del modelo: las veinte predicciones inglesas históricas no registraron la huella de la voz separada que recibieron. Las voces actuales combinan siete separaciones del Mac y trece de un runner. PPG rechazó contornos FCPE de otra separación y los regeneró sobre la voz exacta de su ensayo. Las diferencias frente a la base describen la cadena evaluada; las comparaciones entre brazos nuevos sí comparten exactamente la misma voz. No se atribuye toda variación exclusivamente al detector de notas.

Los cinco controles actuales exigen WER ≤5 %, p90 del error temporal de las palabras coincidentes ≤120 ms, clase de altura correcta ≥90 %, F1 de ataque y clase de altura ≥0,85 y precisión sobre los fotogramas que el mapa pide puntuar ≥90 %. El emparejamiento de ataques admite ±100 ms. Las métricas de altura comparan clases de nota y no penalizan diferencias de octava. El último control penaliza también extender notas hacia silencios o clases de nota incorrectas; no equivale sólo a acertar su comienzo. Se añade como objetivo experimental más exigente WER ≤1 %, p90 ≤80 ms, clase ≥98 %, F1 ≥0,95 y precisión ≥98 %. Este objetivo no modifica las reglas del producto.

El [nuevo evaluador](../../scripts/experiments/evaluate_generation_candidate.py) separa congelación y evaluación, comprueba identidades y cambios de bytes, cuenta ausencias y rechaza notas fuera de la grabación. Informa también finales de notas emparejadas una sola vez. El [banco de generación](../../scripts/benchmark_generation_corpus.py) deja de aceptar `metrics.json` antes de comprobar su procedencia: un cambio del evaluador recalcula métricas sin cargar modelos; un cambio de audio o generación exige otro directorio.

## Resultados de notas ya completados

| Candidato | Canciones completas | Clase correcta mediana | F1 de ataque mediano | Superan cinco controles |
|---|---:|---:|---:|---:|
| Base GAME con las dos letras corregidas | 40 | 76,48 % | 0,6677 | 0/40 |
| SwiftF0, sólo alturas | 40 | 73,32 % | 0,635 | 0/40 |
| SwiftF0, reconstrucción de eventos | 40 | 59,33 % | 0,559 | 0/40 |
| PPG + FCPE, reconstrucción de eventos | 40 | 64,65 % | 0,5972 | 0/40 |
| PPG, ajuste conservador de límites | 40 | 70,77 % | 0,6565 | 0/40 |

La base de esta tabla es la predicción automática sin corregir intervalos mediante la referencia. El turno de **Amorfoda** recuperable en 0.3.1 sí superó la admisión después de esa corrección independiente. Ese resultado no demuestra que el generador autónomo produjera ya todas sus duraciones correctamente.

Swift completa cuarenta voces en 40,23 s, CPU con dos hilos y pico de 761 MiB, pero empeora altura y ataques. PPG completa el piloto y la extensión en unos cuatro minutos, pico de 1,32 GiB. Su ajuste de límites mejora el F1 con finales en 32 canciones, pero baja la cobertura mediana del 96,05 % al 87,84 % y reduce la clase correcta en las cuarenta. Esa compensación impide promoverlo como mejora general. Ninguna variante alcanza el objetivo experimental más exigente.

Se probaron además cuatro modos de GAME —libre, palabras, sílabas e inicios/finales de sílabas— sobre **dos** canciones completas. En Amorfoda, condicionar por sílabas sube el F1 de eventos de 0,8782 a 0,9032, pero la precisión del tiempo puntuable permanece en 50,31 %. En Northern Star, condicionar por ambos límites llega a F1 0,8391 y precisión 57,90 %. Ninguna pasa los cinco controles. Los límites proceden del mapa predicho después de GAME, no de un alineamiento CTC crudo; tampoco permiten recuperar palabras omitidas por la predicción inicial. Cada evaluación registra dos presentes y treinta y ocho ausentes.

Datos sin audio ni letras: [Swift](generacion-swift-2026-11-21.csv), [PPG](generacion-ppg-2026-11-21.csv) y [piloto GAME condicionado](generacion-game-condicionado-2026-11-21.csv). Predicciones completas, trazas y manifiestos congelados permanecen en `build/generation-next/`.

## SingMelody: cuatro hipótesis sobre cuarenta canciones

Se comprobó la compatibilidad exacta de sus pesos con la arquitectura pública GAME: 671 tensores, sin claves ni dimensiones ausentes. Sin embargo, no estaba disponible el runner oficial que fija la inferencia y el valor de `t`. Se construyó un adaptador experimental y se declararon antes de evaluar cuatro combinaciones: segmentación libre o condicionada por palabras predichas, con `t=0` o `t=1`. Cada una produce un mapa que cambia sólo alturas y otro que reconstruye eventos. Se conservan los ocho conjuntos completos, sin escoger un ganador para cada canción.

Los 320 mapas son válidos y pertenecen a las mismas cuarenta grabaciones; **ninguno de los ocho conjuntos obtiene una canción que supere los cinco controles**, ni el objetivo casi perfecto. La clase correcta mediana queda entre 62,16 % y 66,87 %, frente a 76,48 % de la base; el F1 de ataque también queda por debajo de la base en todas las variantes. Algunos eventos libres mejoran ligeramente el F1 que incluye finales, a costa de otras métricas. No se promueve esta reconstrucción al producto. El resultado no es una reproducción oficial ni una conclusión general sobre todo uso posible de SingMelody.

El piloto de cuatro canciones tardó 127,11 s y la extensión de treinta y seis, 1.301,15 s; esta última tuvo un máximo residente de aproximadamente 690 MiB, con dos hilos CPU y sin intercambios a disco. El [CSV de 360 filas](generacion-singmelody-2026-11-21.csv) incluye los ocho conjuntos y la base, con todas las canciones. La [investigación de modelos](research-generacion-modelos-2026-11-21.md) conserva configuración, fuentes, hashes, métricas por idioma y límites del ensayo.

## Reconocimiento de letra: piloto y cuarenta canciones

Se prueba Qwen3-ASR 1.7B Q4_K con una conversión fijada por revisión y SHA-256, a través del CrispASR 0.8.54 ya instalado para experimentos. Las canciones se procesan completas en bloques acotados, sin introducir su texto humano ni reproducir audio. El reconocimiento usa Metal; la evaluación usa exactamente la normalización de palabras del proyecto. No se deduplican repeticiones reales entre bloques.

| Canción completa | WER de la base | Qwen, voz separada | Qwen, mezcla original |
|---|---:|---:|---:|
| Amorfoda | 1,38 % | 54,48 % | 32,41 % |
| Northern Star | 3,37 % | 14,04 % | 2,25 % |

El piloto no respalda una sustitución general: la mezcla mejora Northern Star pero empeora Amorfoda; la voz separada empeora ambas. Cada informe del piloto mantiene dos evaluadas y treinta y ocho ausentes. Ninguna llega al objetivo de ≤1 % WER.

La ampliación procesó las cuarenta mezclas originales en 17 min 13 s, con pico RSS de 1,81 GiB, sin fallos ni canciones ausentes. Se fijaron bloques de 28 s, sin solapamiento y con límite de 512 tokens; no se eligió para cada canción la variante que más se acercase a su referencia.

| Cohorte | WER mediana de la base | WER mediana Qwen | Mejora / empeora / igual |
|---|---:|---:|---:|
| Cuarenta canciones | 6,72 % | 14,49 % | 9 / 30 / 1 |
| Veinte españolas | 7,88 % | 17,48 % | 3 / 17 / 0 |
| Veinte inglesas | 5,63 % | 10,80 % | 6 / 13 / 1 |

Los resultados con WER ≤5 % bajan de 17 a 7; los de ≤1 %, de 4 a 0. La base incluye letras corroboradas por otras fuentes, mientras Qwen recibe sólo audio: la tabla compara estas cadenas, no demuestra una superioridad general de Whisper sobre Qwen. No se adopta esta configuración como sustituto. El [CSV de cuarenta canciones](generacion-qwen-2026-11-21.csv) conserva las diferencias por grabación; revisión, hashes y protocolo están en [el informe del ensayo](research-generacion-pipelines-2026-11-21.md). Estos números evalúan sólo palabras, no sus tiempos ni la melodía, y describen esta conversión y configuración del reconocedor.

## Diagnóstico de intervalos y selección acústica de letra

La comprobación de intervalos explica por qué mejorar sólo el detector de alturas no basta. El generador pide puntuar 1,518 veces el tiempo anotado por las referencias. Incluso acertando todas las alturas, mantener esos intervalos limitaría la precisión mediana al 60,98 %: ninguna canción alcanzaría el 90 %. El 70,26 % de los instantes incorrectos está en huecos internos de los mapas humanos. Esos huecos no demuestran silencio acústico ni permiten atribuir automáticamente el error a coros. Un parser racional independiente y la integración continua descartan que el desfase de ticks o el muestreo de 10 ms expliquen la magnitud de la diferencia. El [diagnóstico de intervalos](generacion-diagnostico-intervalos-2026-11-21.md) conserva el desglose completo y sus límites.

Se probó además elegir la letra completa entre la base y Qwen usando probabilidades acústicas de Sylla ya guardadas. Se fijaron cuatro reglas antes de consultar las referencias. La primaria mejora seis canciones y empeora cuatro; mantiene la mediana WER en 6,72 %, con 17/40 dentro del 5 % y 4/40 dentro del 1 %. Una probabilidad acústica mayor no garantiza acertar el texto: en «Amorfoda» la regla escoge una transcripción peor. Ninguna variante justifica una sustitución general. El [informe de selección acústica](research-letra-acustica-2026-11-21.md) y su [CSV de 240 filas](generacion-letra-acustica-2026-11-21.csv) incluyen base, Qwen y las cuatro reglas sin selección retrospectiva por canción.

Este cálculo usa una recurrencia CTC con filas reutilizables, comprobada contra enumeración exacta de caminos sintéticos. Las cuarenta canciones tardaron 68,79 segundos y unos 46 MiB residentes, sin cargar modelos ni GPU. Evalúa palabras; no aporta una mejora demostrada de tiempos o notas.

## Incidencia del separador experimental

El ensayo de BS Roformer de voz principal coincidió con un reinicio del Mac por watchdog. La presión de memoria de la atención temporal en ventanas de veinte segundos es el desencadenante probable, sin demostrar una causa exclusiva del fallo del núcleo. Aquel ensayo no completó ninguna separación musical ni se incorporó al producto.

Se retiró MPS del adaptador y se limitaron las ventanas de continuación a cuatro segundos en CPU. Además de la estimación previa, ahora se observa cada 50 ms el RSS y la huella física del trabajador real; si alcanza 1,5 GiB, pierde la telemetría o agota su plazo, se detiene y se confirma su cierre. Quince pruebas comprueban las guardias sin cargar el modelo. El muestreo no garantiza capturar todos los picos instantáneos.

Después del control sintético se separó **Amorfoda completa**, 176,855 segundos, en 534,43 segundos totales. Se conservaron todas sus muestras y la salida es finita; los máximos observados fueron 1.290,38 MiB RSS y 1.208,31 MiB de huella física. Es una ejecución musical terminada en el M4, no una validación de precisión del mapa ni del conjunto de cuatro canciones previsto. El [informe de voz principal](research-voz-principal-2026-11-21.md) conserva audio, hashes y recursos. El [informe del incidente](reinicio-experimento-2026-11-21.md) documenta la causa probable y las medidas preventivas. La instalación pública 0.3.1 conserva su código original.

## Ensamblado, consenso y nuevas hipótesis

La reconstrucción del ensamblado de GAME reproduce los dieciséis mapas de los ocho pares del piloto anterior. No añade tiempo puntuable ni rellena huecos entre notas iguales; entre el 98,15 % y el 99,41 % del tiempo incorrecto ya está en los eventos que recibe. El [diagnóstico](generacion-game-ensamblado-2026-11-21.md) no prueba todavía el ensamblado interno de ventanas: los eventos guardados ya habían pasado por él. Los ensayos nuevos conservan también las ventanas crudas para poder distinguir ambas etapas.

Un consenso predeclarado entre SOME y ROSVOT acorta 283 notas de 39 canciones. Retira 22,892 segundos incorrectos, pero también 6,158 segundos correctos. La precisión mediana apenas pasa de 50,260 % a 50,365 % y el acierto de clase sobre la referencia baja de 76,475 % a 76,170 %. Continúa en **0/40** tanto en las cinco puertas como en el criterio casi perfecto. Se conserva como resultado negativo; no se promueve. El [informe y CSV completo](generacion-finales-consenso-2026-11-21.md) documentan el candidato único y su auditoría independiente.

Se comparó además [YourMT3+](research-finales-nota-2026-11-21.md), que predice eventos y distingue voz y coro. Tras revisar recursos, cuatro procesos secuenciales terminaron las cuatro canciones del piloto en 326,625 segundos, con máximo observado de 2.211,28 MiB RSS. La reconstrucción de eventos mejora el F1 con finales en las cuatro, pero reduce también clase correcta y cobertura en las cuatro; **0/4 supera los cinco controles o el objetivo estricto**. Se conservan 36 ausentes en cada conjunto. La [evaluación y CSV](generacion-yourmt3-2026-11-21.md) no justifican promoverlo ni extrapolar el piloto a cuarenta canciones.

Para letra se investigan [HeartTranscriptor y cortes por energía vocal](research-letras-siguientes-2026-11-21.md). La segmentación propia ya procesó las cuarenta voces sin modelos: 557 fragmentos, 4,157 segundos y 52,547 MiB RSS, conservando todas las exclusiones. Está [preparada una comparación acústica](research-letras-rms-asr-2026-11-21.md) de dieciséis condiciones sobre cuatro canciones, pendiente de comprobar la carga del reconocedor. Ninguna de estas preparaciones aporta todavía una mejora demostrada a los cuarenta mapas.

## Investigación reutilizable

Se inspeccionaron código, pesos, licencias y documentación originales de UltrastarCreatorTool, UltraSinger, UltraStarKaraokeMaker, AutoKaraoke, GAME, SwiftF0, el modelo fonético de ICASSP 2023, Qwen3-ASR, VocalParse y SingMelody. Actualizar la revisión de Creator no cambia sus algoritmos de notas o alineación. Algunos modelos recientes carecen de inferencia pública reproducible, no generan tiempos absolutos o sólo han demostrado resultados condicionados a texto correcto.

Las fuentes y limitaciones están documentadas en [pipelines reutilizables](research-generacion-pipelines-2026-11-21.md) y [modelos de notas](research-generacion-modelos-2026-11-21.md). El [informe original de Qwen, sección 4.4](https://arxiv.org/html/2601.21337v1#S4.SS4), justifica probar su reconocedor de canto, distinto del alineador ya evaluado. Su cifra de 14,60 % WER en un conjunto interno inglés con acompañamiento no describe nuestro corpus, español ni la conversión GGUF utilizada aquí.

Todos estos ensayos se ejecutan localmente en el Mac M4, sin reproducir las canciones ni capturar voz. El estado final de la salida del Mac es silenciado. Son medidas de inferencia y precisión; no constituyen validación de instalación ni rendimiento de estos modelos en Windows.

## Resultado de la continuación

Se conservan los adaptadores, métricas y fuentes para reproducir o ampliar los ensayos; no se reemplaza el generador del producto con una configuración que haya empeorado. La descarga accesible, la transcripción correcta y el mapa puntuable son requisitos distintos: disponer de un descargador de YouTube no resuelve los dos últimos, y algunos vídeos requieren autenticación o no están disponibles para el entorno ensayado. El acceso a cualquier vídeo y la fiabilidad casi perfecta siguen sin demostrarse.

En paralelo sí se incorporan correcciones con regresiones reproducidas: [continuidad del reloj móvil al pausar y recibir audio discontinuo](sincronia-movil-2026-11-21.md) y [estado de preparación/revisión visible sin perder la edición en el mando](mando-ux-2026-11-21.md). La rama de desarrollo conserva estas mejoras; la publicación 0.3.1 sigue identificando su commit original. Aprobar un borrador continúa siendo un paso explícito en el ordenador: estos resultados no justifican ocultarlo ni marcar automáticamente como listas las nuevas predicciones.
