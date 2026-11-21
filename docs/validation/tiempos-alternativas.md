# Alineación del canto en las mismas 40 grabaciones

## Qué reloj medimos

El ensayo comprueba si la letra y las notas de un mapa generado coinciden con la interpretación que anotó una persona. Cada predicción recibe la mezcla elegida, su voz separada y el borrador producido por Karaoke. El evaluador abre el mapa humano cuando ya existe la huella SHA-256 de cada predicción. Una edición de estudio puede tener otra entrada vocal, un puente más corto o un final distinto al del videoclip. Por eso fijamos la grabación completa y su identidad antes de comparar técnicas. DALI también tuvo que comprobar la correspondencia entre grabaciones y anotaciones colaborativas al construir su colección. [Muestra fijada](generacion-muestra.json) · [Publicación original de DALI](https://archives.ismir.net/ismir2018/paper/000035.pdf)

El ataque de una palabra, el inicio de su vocal y el instante en que se estabiliza la altura pueden caer en fotogramas distintos. En un melisma una sílaba contiene varios cambios de nota. En un pasaje hablado puede haber frecuencia fundamental y ritmo sin un objetivo de afinación inequívoco. Un clasificador de rap/canto publicado por Fraunhofer trabajó con segmentos de voz aislada y observó que el acompañamiento influía mucho sobre su clasificación. La investigación sobre canto de Gong y Serra combina inicios de sílaba, fonemas y un modelo de duración. Huang, Benetos y Ewert mostraron que entrenar conjuntamente la altura y los límites de las frases mejora la alineación. Estas tareas miden aspectos distintos del problema. [Canto y rap en pistas vocales aisladas](https://archives.ismir.net/ismir2010/paper/000088.pdf) · [Segmentación de canto a nivel de fonema y sílaba](https://arxiv.org/abs/1806.01665) · [Alineación conjunta con altura](https://arxiv.org/abs/2202.01646)

## Alternativas comparadas

Todos los métodos usan la misma letra de entrada para cada grabación. Los límites y ventanas son comunes a todas las canciones. Las predicciones de pulso y de transitorios funcionan por separado y las alternativas conservan el orden de las barras.

| Método del CSV | Señal y decisión |
|---|---|
| `base` | Salida completa del generador de Karaoke. La alineación cantada CTC y los eventos musicales de GAME ya formaban parte de esta base. |
| `pulso` | Beat This! detecta los pulsos en la mezcla. Se acerca cada ataque a la subdivisión de semicorchea más cercana cuando está a 65 ms o menos. |
| `ataque` | En la voz aislada se calculan cambios de energía en bandas logarítmicas cada 5 ms. Un filtro máximo de frecuencia atenúa el efecto del vibrato. Se usa un pico local a un máximo de 65 ms. Es una implementación propia inspirada en SuperFlux. |
| `doble` | Se corrige hacia el promedio del pulso y del transitorio vocal cuando sus estimaciones distan 35 ms o menos. |
| `palabra` | Se emparejan palabras iguales, en orden, entre la letra del borrador y las palabras que oyó Whisper. Cuando sus comienzos distan hasta 140 ms se desplaza el primero un 40 % de esa diferencia. |
| `ornamentos` | Se absorbe una continuación melismática de hasta cinco ticks (83 ms) si sigue inmediatamente a la anterior y dista dos semitonos o menos. Se conserva el espacio de final de palabra. |
| `qwen` | Qwen3-ForcedAligner recibe la voz aislada y un conjunto de palabras de la letra. Trabaja con ventanas ancladas aproximadamente a las frases del borrador. Se aceptan duraciones positivas y discrepancias de inicio de hasta 250 ms. |
| `qwen-consenso` | Dentro de cada ventana se exige corroboración de al menos el 70 % de las palabras. Las de hasta 160 ms de discrepancia se desplazan la mitad. |
| `consenso-completo` | Conserva los tiempos de `qwen-consenso` y cambia la clase vocal sólo donde SOME y ROSVOT proponen independientemente la misma clase. |
| `sylla-principal` | Sobre la mezcla original, Sylla produce probabilidades de grafemas de la voz principal cada 20 ms. Un alineador CTC fija cada grafema a la letra generada y usa el primero de cada sílaba como candidato de ataque. |
| `sylla-dos-voces` | El mismo alineador usa la media de las probabilidades de voz principal y coros. Se normaliza la distribución completa de cada voz antes de seleccionar los grafemas de trabajo. |
| `sylla-acuerdo` | Ambas salidas han de coincidir a 40 ms o menos. Si el ataque está a menos de 160 ms del borrador se aplica la mitad de la corrección media. |
| `sylla-vocal` | Se ensaya el inicio de la primera vocal ortográfica de la sílaba. Se requieren evidencia acústica y un intervalo de consonante a vocal de 180 ms o menos. |
| `sylla-intervalo` | Se mantiene cualquier ataque que caiga entre el primer grafema y la primera vocal. Cuando ambas cabezas coinciden en ambos extremos a 40 ms o menos, se corrige la mitad de la distancia al extremo más cercano, con discrepancia de hasta 160 ms. |

Beat This! sigue el pulso en repertorios y tempos diversos. Su artículo documenta fallos de continuidad incluso cuando el F1 global es alto. El original de SuperFlux explica la supresión de falsos ataques por vibrato. Qwen3-ForcedAligner acepta español e inglés. La conversión Q4_K utilizada ocupa 529.001.216 bytes y asigna clases de tiempo en pasos de 80 ms. Una palabra musical corta puede ocupar uno o dos de esos pasos. [Artículo de Beat This!](https://arxiv.org/abs/2407.21658) · [Pesos y código del detector](https://github.com/CPJKU/beat_this) · [SuperFlux](https://www.dafx.de/paper-archive/details/0oee-99Z88WL7pSo749gcA) · [Modelo original de Qwen](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B) · [Conversión de CrispASR](https://huggingface.co/cstr/qwen3-forced-aligner-0.6b-GGUF)

## Qué revelan los ataques

La muestra contiene veinte grabaciones en inglés y veinte en español. Han pasado por el generador completo. Las veinte inglesas se volvieron a generar en Windows con la edición pública verificada. Catorce borradores coinciden byte a byte con la comparación anterior. Las seis diferencias corresponden a canciones que usaron transcripción automática en ambas ejecuciones. Todas las comparaciones de esta iteración fijan el mismo borrador por canción. [Ejecución inglesa](https://github.com/AlexAmMo/karaoke/actions/runs/44913555763) · [Métricas por canción](tiempos-por-cancion.csv)

| Mediana por canción del borrador | Inglés | Español |
|---|---:|---:|
| Error de palabras (WER) | 6,69 % | 9,75 % |
| Error del inicio de palabra, percentil 90 | 74 ms | 139,5 ms |
| Clase vocal correcta en todos los fotogramas anotados | 78,79 % | 71,54 % |
| Techo de F1 dado el número de barras producidas y anotadas | 0,956 | 0,938 |
| F1 de ataques dentro de 50 ms | 0,732 | 0,440 |
| F1 de ataques dentro de 100 ms | 0,904 | 0,783 |
| F1 de ataque dentro de 100 ms y clase correcta | 0,725 | 0,610 |

El techo de recuento es dos veces el menor número de notas dividido por la suma de ambos recuentos. Incluso permitiendo cualquier fecha o altura, producir demasiadas o demasiado pocas barras limita ese techo. Cuando se exige acertar el instante y después la clase aparecen otras dos pérdidas. La diferencia entre lenguas incluye las diferencias de artistas, estilos, procedencia de los mapas y disponibilidad de letra en esta colección. Once canciones inglesas son de Jonathan Coulton.

### Cinco cambios económicos

Los cinco ajustes se probaron en las cuarenta grabaciones. El generador base superó el objetivo de WER en 15, el de p90 en 22, el de clase en 2 y el de F1 conjunto en 1. Ninguna cumplió los cuatro a la vez con los textos y tonos de partida. Las alternativas siguientes conservaron esos mismos textos. Para estimar efectos fuera de los dos casos que se estudiaron durante el desarrollo se excluyeron `northern-star` y `bad-bunny-amorfoda`. Cada diferencia de esta tabla compara dos predicciones de la misma grabación. [Resultados individuales](tiempos-por-cancion.csv)

| Cambio en las otras 38 | Δ p90 mediano | Δ clase mediana | Δ F1 mediana | Canciones con F1 mejor / igual / peor |
|---|---:|---:|---:|---:|
| Subdivisión del pulso | +6,5 ms | −0,46 pp | −0,00465 | 11 / 2 / 25 |
| Transitorio de la voz aislada | +7,5 ms | +0,24 pp | −0,00075 | 12 / 7 / 19 |
| Acuerdo entre pulso y transitorio | 0 ms | +0,25 pp | 0 | 17 / 7 / 14 |
| Palabra corroborada por Whisper | −0,5 ms | +0,58 pp | 0 | 15 / 8 / 15 |
| Absorber el melisma breve | 0 ms | −0,08 pp | +0,00090 | 24 / 3 / 11 |

El transitorio puede señalar la consonante, un golpe de percusión residual o una respiración. Mover cada barra hacia él empeora la precisión de las palabras en la canción mediana. La opción de acuerdo mejora el F1 mediano en 0,0025 al dar un solo voto a cada uno de los 27 artistas de ese subconjunto. En 14 canciones el F1 individual baja y el p90 mediano queda igual. Estos resultados apoyan mantener los tiempos originales como comportamiento general.

### Combinar alturas y adornos

Aplicamos además el mismo diseño factorial a los cuarenta textos finales. Treinta y ocho son idénticos a los originales. En *Amorfoda* se sustituyó la letra por texto corroborado de esa misma grabación y en *Northern Star* se corrigió la ortografía de palabras corroboradas por la transcripción. Son los dos casos de desarrollo. Las cuatro combinaciones usaron la misma letra y conservaron el momento de cada palabra. Se comprobó que los 160 mapas tenían barras ordenadas y cero ataques duplicados o notas solapadas. Cuatro canciones produjeron exactamente la misma salida con y sin absorción de adornos. [Factorial por grabación, huellas y recuentos](tiempos-consenso-adornos.csv)

| Texto final | Aprobadas / 40 | F1 de *Amorfoda* | F1 de *Northern Star* | Δ F1 mediana en las otras 38 |
|---|---:|---:|---:|---:|
| Tono y divisiones originales | 1 | 0,8756 | 0,8394 | 0 |
| Consenso SOME + ROSVOT | 1 | 0,8844 | 0,8474 | −0,01015 |
| Adornos absorbidos | 1 | 0,8756 | 0,8466 | +0,00090 |
| Consenso y adornos absorbidos | 2 | 0,8844 | 0,8548 | −0,00870 |

En *Northern Star* se absorben nueve continuaciones. La combinación obtiene 3,37 % WER, p90 de 67 ms y 91,09 % de clase. En *Amorfoda* supera los umbrales con 1,38 % WER, p90 de 63 ms y 91,45 % de clase. En las otras 38 canciones, la combinación mejora el F1 en nueve y lo empeora en 29. Al agrupar primero por artista mejoran cinco de 27 y empeoran 22. Si además se excluyen *Mr. Fancy Pants* y *11 y 6*, usados como controles durante el desarrollo, el efecto mediano por artista es −0,00945 en F1. Un sistema que siempre elija esta variante degradaría muchos mapas. Cuando se dispone de una verificación independiente, tiene sentido evaluar la combinación como un candidato adicional.

### Qwen y la coincidencia por palabra

Con los textos de partida, Qwen directo aumentó el p90 de la canción mediana en 25 ms y bajó su F1 en 0,03075. El modo conservador dejó ambas medianas pareadas iguales y elevó la coincidencia de clase en 0,96 puntos porcentuales. Sobre las dos letras corregidas, el cruce del modo conservador con el consenso de alturas también alcanza los cuatro umbrales en ambas canciones. *Northern Star* obtiene 3,37 % WER, p90 de 67 ms, clase de 92,71 % y F1 de 0,8514. *Amorfoda* consigue 1,38 %, 82 ms, 92,37 % y 0,8733 respectivamente. Este cruce y el de adornos contabilizan los mismos dos títulos. En las otras 38 grabaciones el cruce de Qwen y consenso de alturas empeora el F1 en 26, con un cambio mediano de −0,0135. [Mapas comparables de las cuarenta grabaciones](tiempos-por-cancion.csv) · [Dos casos de letra corregida](tiempos-textos-corregidos.csv)

### Comprobar voz principal y coros

Sylla-600M predice alineación de las sílabas de la voz principal con una segunda salida para coros. Sus autores publican resultados de JamendoLyrics en cuatro idiomas y comunican que el 92,9 % de los inicios de palabra cae a menos de 200 ms. La evaluación de Karaoke exige p90 de palabra ≤120 ms por grabación, además de notas correctas. El modelo principal pesa 2,33 GB y su ficha indica que se entrenó con grabaciones comerciales y sílabas anotadas. La ficha carece del listado con el que descartar solapamientos de artistas con esta muestra. [Modelo y evaluación de Sylla](https://huggingface.co/radiant-lyrics/sylla-600m-v1)

| Alineación cantada sobre 40 canciones | Δ p90 mediano pareado | Δ clase mediana pareada | Δ F1 mediana pareada | F1 mediano inglés | F1 mediano español |
|---|---:|---:|---:|---:|---:|
| Base | 0 ms | 0 pp | 0 | 0,725 | 0,610 |
| Primer grafema de voz principal | +35 ms | +2,73 pp | −0,07970 | 0,632 | 0,534 |
| Primer grafema de ambas voces | +28 ms | +1,86 pp | −0,06460 | 0,670 | 0,536 |
| Primer grafema con acuerdo | 0 ms | +1,66 pp | −0,00235 | 0,723 | 0,616 |
| Primera vocal | +16 ms | +1,24 pp | −0,04530 | 0,691 | 0,565 |
| Conservar el intervalo consonante–vocal | 0 ms | +0,17 pp | 0 | 0,726 | 0,612 |

El intervalo conservador deja el p90 español en 139,5 ms. En las cuarenta canciones mejora el F1 en 13, lo conserva en 17 y lo empeora en 10. La alternativa directa que usa el primer grafema de la voz principal mejora la coincidencia de clase en muchos fotogramas, pero empeora el F1 conjunto en 34 canciones. En este ensayo la fecha fonética que asigna el modelo y la fecha musical que necesita el karaoke son dos objetivos diferentes. Ninguna de las variantes cantadas aprueba una canción adicional con los textos originales. [Comparación cantada independiente](tiempos-por-cancion.csv)

### Coste y controles de reproducción

Las 40 predicciones Qwen de la matriz principal se hicieron sobre la voz congelada en el mismo backend Metal del Mac. En un lote aislado de doce temas ingleses, más la repetición con la letra corregida de *Northern Star*, la mediana de la etapa de alineación fue 4,27 s por canción (3,16–6,47 s). Los cuatro controles CC que reprodujeron exactamente la voz en otro equipo se ejecutaron también en CPU Linux. De 1.025 palabras, dieciséis devolvieron una marca o validez distinta entre CPU y Metal. Las otras nueve reconstrucciones del runner quedaron excluidas por tener una huella diferente incluso después de restaurar los cuatro bytes de la hora de escritura que libsndfile guarda en la cabecera WAV. [Control de Qwen en Linux](https://github.com/AlexAmMo/karaoke/actions/runs/44920032761)

Para Sylla, los cinco runners CPU produjeron las dos salidas de las veinte mezclas inglesas. Los runners consultaron además las veinte URLs españolas directamente en YouTube. Dieciséis exigieron iniciar sesión y cuatro devolvieron otro error de proveedor. Las veinte mezclas españolas ya verificadas se procesaron en el Mac cargando una capa del modelo cada vez. El control de dos canciones duró 24,64 s y las otras diecinueve españolas, 4 min 43 s en un único proceso. En el control inglés de 3.976 fotogramas, la clase de grafema más probable de CPU y Metal coincide en 3.975 en la voz principal y en todos al combinar las voces. El mapa de voz principal y el de acuerdo conservador coincidieron byte a byte. El mapa de ambas voces presentó diferencias. Estas duraciones miden el alineador con los recursos anteriores ya disponibles. [Emisiones inglesas](https://github.com/AlexAmMo/karaoke/actions/runs/44916006377) · [Comprobación remota de las fuentes españolas](https://github.com/AlexAmMo/karaoke/actions/runs/44918613363)

## Otros sistemas relacionados

SingMelody acepta palabras y fonemas alineados y decide el número y tono de los eventos dentro de cada palabra. Su ficha distingue idiomas y declara que la densidad de notas internas anotadas varía por un factor de 5,2 entre ciertos idiomas del corpus de entrenamiento. Una evaluación útil debe conservar los ataques por sílaba y las curvas ornamentales por separado. Un estudio de técnicas vocales en J-pop muestra ejemplos anotados por técnica de voz y documenta que los coros o instrumentos similares a la voz principal pueden permanecer en la pista separada. [SingMelody](https://huggingface.co/pymaster/SingMelody) · [Anotaciones de técnicas vocales](https://archives.ismir.net/ismir2022/paper/000046.pdf)

El alineador Echora v8 incorpora una segunda salida para voz de fondo y se entrenó con voces separadas. Sus autores describen errores en interjecciones repetidas, voces solapadas, pasajes de rap y notas sostenidas. Su licencia limita el uso a proyectos personales y prohíbe redistribuir los pesos. [Ficha de Echora](https://huggingface.co/hcX02/echora-mms-300m-multilingual-lyrics-forced-aligner)

## Reproducción

Se necesitan los 40 archivos de audio y sus mapas de referencia en un directorio privado, las huellas fijadas en el manifiesto y un borrador generado por cada entrada. `charts.json` asocia cada identificador a su `draft.txt`. El `acoustics.json` de esa misma ejecución contiene los tiempos de Whisper y `metrics.json` certifica la mezcla y la salida. `stems.json` asocia cada identificador a la voz separada de esa mezcla mediante HTDemucs. El directorio de trabajo también contendrá letras y mapas generados.

1. Ejecutar `timing_beats.py` con el manifiesto de preparación, el modelo `final0.ckpt` y el directorio de pulsos. La revisión de Beat This! utilizada es `b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c`, la de `rotary-embedding-torch` es 0.8.9 y el SHA-256 del modelo es `8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331`.
2. Ejecutar `timing_features.py` con `stems.json` y el directorio de características de la voz. Ejecutar `timing_predict.py` con `charts.json`, el directorio de pulsos, el de características, el de predicciones y `--stems stems.json`. Esta última comprobación lee y verifica la huella de la voz exacta utilizada para cada espectro.
3. Ejecutar `timing_neural.py` con la biblioteca compartida de CrispASR 0.8.54, el GGUF Q4_K verificado por el script, `charts.json`, `stems.json` y un directorio de predicciones neuronales. El modelo admite CPU o GPU. Se descarga de memoria al final de cada grupo de hasta cuatro canciones. `timing_fusion.py` verifica las huellas del consenso de altura y del de tiempo antes de escribir el mapa combinado. [Biblioteca y distribuciones nativas](https://github.com/CrispStrobe/CrispASR/releases/tag/v0.8.54)
4. Para Sylla, ejecutar `timing_sylla_emissions.py` con la mezcla, sin letra, y después `timing_sylla.py` con la letra del borrador y las emisiones. Para el modo usado en este Mac, `timing_sylla_stream.py` recibe el manifiesto, los pesos, la salida y los parámetros `--device mps --group 3`. La revisión del modelo es `0a228acf0c1351ad0e2734604ee921d497d861e8`. Los scripts comprueban las huellas de las dos cabezas, esperan 20 ms por fotograma y rechazan resultados no finitos o de tamaño incompatible. Cada ventana tiene 24 s de núcleo y 2 s reales de contexto por lado. Se descartan los márgenes antes de unir las ventanas.
5. Ejecutar `timing_evaluate.py` con el manifiesto local, `charts.json`, las predicciones y el CSV de destino. Los argumentos `--qwen`, `--fusion` y `--sylla` incorporan las variantes adicionales. El modo completo verifica la cohorte, los másteres, las referencias y las huellas de cada predicción. `timing_ornament_consensus.py` separa la generación de las cuatro combinaciones de adornos/consenso del comando que abre las referencias y las evalúa.

Las métricas de ataque emparejan uno a uno. El F1 de ataque y altura exige la misma clase cromática a ±100 ms. Se exponen también los F1 a 50 y 100 ms con el tiempo como único requisito. Así se puede ver cuánto error procede de elegir otro tono para un ataque que sí estaba localizado. Cada tercio de la canción informa del adelanto o retraso mediano de las palabras emparejadas. La metodología de mir_eval también diferencia métricas sólo de ataque y métricas conjuntas de ataque, liberación y altura. [Métricas de transcripción de mir_eval](https://mir-eval.readthedocs.io/stable/api/transcription.html)
