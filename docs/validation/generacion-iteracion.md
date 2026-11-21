# Generar una canción puntuable a partir de su grabación

Karaoke ya puede analizar la mezcla original y producir un paquete UltraStar auditable. La voz del artista permanece en la reproducción. El separador, la transcripción y la estimación musical trabajan sobre una copia temporal. Un mapa generado empieza como borrador y requiere revisión para entrar en la biblioteca. La selección de canciones con un mapa comunitario verificado mantiene su flujo habitual.

## Cómo se obtiene cada componente

1. **Grabación.** El trabajo de la aplicación conserva el identificador del vídeo elegido, limita la descarga a ese vídeo y vincula el paquete a la huella SHA-256 del audio. El generador decodifica la pista, separa la voz con HTDemucs y vuelve a usar la mezcla para el MP3 reproducible. [Demucs](https://github.com/facebookresearch/demucs)
2. **Letra.** Whisper large-v3-turbo reconoce las palabras cantadas. Se puede aportar la letra, aprovechar subtítulos manuales del mismo vídeo o consultar LRCLIB. Para estos últimos se exige título, intérprete, duración compatible y coincidencia ordenada con las palabras reconocidas. Los tiempos del fichero de letras se descartan. Una letra aportada que diverge claramente de una transcripción suficientemente larga da un error. [Modelo Whisper](https://huggingface.co/openai/whisper-large-v3-turbo) · [API de LRCLIB](https://lrclib.net/docs)
3. **Sílabas.** Un alineador CTC entrenado con voz cantada asigna las sílabas a la interpretación concreta. Una puerta de energía ayuda a evitar los silencios. Un estimador de frecuencia fundamental sitúa el comienzo de la voz. El adaptador de UltrastarCreatorTool procede de una revisión concreta de código GPL y se comprueba al instalar. [Alineador de Tune Studio](https://huggingface.co/tuneperfect/tunestudio-aligner) · [Adaptador y evaluación de seis canciones](https://github.com/retotito/UltrastarCreatorTool/blob/39d3eb5f9fb1e24220c4ca58888af8a88e11a38a/docs/decisions/0002-forced-alignment-of-user-lyrics.md)
4. **Notas.** GAME extrae ataques, finales y alturas en ventanas de 12 s con contexto solapado. La app asocia esos eventos con las sílabas. Un cambio de nota dentro de una misma vocal conserva la prolongación del texto. El final puede extenderse mientras hay eventos vocales continuos. Las palabras sin tono identificable quedan sin puntuación. Una segunda medición con FCPE señala fragmentos en los que conviene escuchar el original. [GAME](https://github.com/openvpi/GAME) · [FCPE](https://github.com/CNChTu/FCPE)
5. **Resultado.** La publicación local del borrador es atómica. El manifiesto contiene las huellas del audio y del TXT, la fuente de letra, las revisiones de modelos y los instantes de baja confianza. El editor permite oír y corregirlos antes de aprobar el paquete. El perfil estándar usa Whisper y pYIN, con menor resolución musical. [Generador](../../src/karaoke/generation_worker.py) · [Dependencias del entorno aislado](../../src/karaoke/generation_assets/requirements.in)

El perfil musical usa pesos no comerciales del alineador (CC BY-NC 4.0) y de GAME (CC BY-NC-SA 4.0). Se obtienen tras elegir ese perfil. El código del proyecto, el código de los motores y los pesos tienen condiciones diferentes. [Pesos de GAME](https://github.com/openvpi/GAME#license) · [Condiciones del alineador](https://huggingface.co/tuneperfect/tunestudio-aligner)

## Qué aportaron las alternativas examinadas

UltraSinger reúne transcripción y estimación de tono en un conversor UltraStar. UltraStarKaraokeMaker parte de una letra que ya se conoce y la alinea con la voz. La distinción importa cuando el reconocedor se salta una palabra o confunde un estribillo. Hemos hecho opcional la letra corroborada para que la vía de solo audio siga funcionando sin cuentas adicionales. [UltraSinger](https://github.com/rakuri255/UltraSinger) · [UltraStarKaraokeMaker](https://github.com/walterfr/UltraStarKaraokeMaker)

SOFA aborda la alineación de voz cantada. ROSVOT y SOME abordan la transcripción melódica. Basic Pitch obtiene MIDI de audio y admite polifonía. GAME publica pesos ejecutables con ONNX y separa la estimación de límites de la estimación de altura. Elegimos esa ruta porque permite probar el resultado contra un mapa humano en los dos sistemas de escritorio que usa Karaoke. [SOFA](https://github.com/qiuqiao/SOFA) · [ROSVOT](https://github.com/RickyL-2000/ROSVOT) · [SOME](https://github.com/openvpi/SOME) · [Basic Pitch](https://github.com/spotify/basic-pitch) · [GAME](https://github.com/openvpi/GAME)

Wav2Karaoke probó una cadena completa en inglés y documentó la pérdida de precisión al combinar reconocimiento, segmentación y notas. Tune Studio publicó una evaluación en 74 canciones inglesas y alemanas con F1 de nota de 0,698 y exactitud de altura de 0,851 con su cadena completa. Sus métricas, idiomas y selección de canciones difieren de los de Karaoke. Sus refinadores de nota usan vectores de características cuya construcción exacta también es parte del sistema. [Wav2Karaoke, Universidad de Tohoku](https://keisuke-sakaguchi.github.io/assets/pdf/2026_nlp_wav2karaoke.pdf) · [Tune Studio](https://huggingface.co/tuneperfect/tunestudio-aligner) · [Refinadores](https://huggingface.co/tuneperfect/tunestudio-note-refiners)

## Iteraciones y controles

Se usaron *Sigo aquí* y *Go the Distance* para elegir el método de segmentación. El resto de mapas humanos se reservaron para medir resultados. Cada generador recibió audio y metadatos o una letra procedente de una fuente independiente. El comprobador abrió el mapa de referencia al calcular errores. No se corrigió el desfase de cada mapa para favorecer las métricas. Los borradores y las grabaciones permanecieron en directorios de trabajo privados.

| Variante sobre «Sigo aquí» | Error de palabras | Inicio de palabra p90 | Clase de nota correcta | F1 de ataques |
|---|---:|---:|---:|---:|
| Whisper small y Praat | 12,3 % | 772 ms | 56,2 % | 0,463 |
| Whisper turbo, letra corroborada, CTC y FCPE por sílaba | 6,4 % | 151 ms | 55,8 % | 0,493 |
| La misma letra con GAME acotado a las sílabas | 6,4 % | 151 ms | 58,0 % | 0,522 |
| GAME libre, ensamble con los eventos vocales reutilizados en desarrollo | 6,4 % | 139 ms | 82,9 % | 0,554 |
| Worker real con separación nueva desde la mezcla | 6,4 % | 139 ms | 81,5 % | 0,558 |

La ejecución real de *Sigo aquí* duró 376,51 s en un Apple M4 con 16 GiB y otras inferencias concurrentes. Sus 432 notas puntuables cubrieron el 95,7 % del tiempo puntuable de la referencia. En el ensayo de desarrollo de *Go the Distance*, una letra independiente redujo el error de palabras de 21,8 % a 5,6 %. En el primer mapa reservado de Fito & Fitipaldis pasó de 8,5 % a 2,3 %. La mejora de letra dejó intacta la necesidad de revisar los ataques musicales. [Medición inicial y definición de métricas](generacion-local-2026-11-21.md)

Probamos seis umbrales entre 60 % y 95 % para que FCPE sustituyera el tono propuesto por GAME cuando el contorno parecía estable. En las dos canciones de desarrollo la exactitud por fotograma empeoró en las seis variantes. El desacuerdo sirve para dirigir la revisión. Desplazar toda la canción 50 ms aumentaba el F1 de *Sigo aquí* y empeoraba el de la grabación de Fito, de modo que se conserva el reloj original. La prueba de silencio rechazó el audio sin señal. Nueve cruces reales entre letras y grabaciones ajenas con metadatos falsamente coincidentes produjeron cero aceptaciones.

## Protocolo de validación

- **Muestra.** Veinte grabaciones en inglés de los paquetes Creative Commons publicados por UltraStar Deluxe y veinte en español con máster identificable de AllKaraoke. Los identificadores y las huellas se fijaron antes de evaluar las notas. Se comprobó la grabación y la sincronía de las ediciones originales. El conjunto inglés sobrerrepresenta a Jonathan Coulton por la distribución del catálogo disponible. Una edición etiquetada simultáneamente como catalana y española resultó ser catalana. Se reservó como control y se incluyó otra grabación cantada en español. [Muestra exacta](generacion-muestra.json)
- **Métricas.** WER de las palabras del mapa, p90 de la distancia absoluta del comienzo de las palabras coincidentes, clase tonal exacta por fotograma de 10 ms sobre todo el tiempo puntuable de la referencia y F1 de ataque con emparejamiento único, misma clase y tolerancia de 100 ms. Una octava de diferencia conserva la clase de nota. Los ataques que sobran o faltan penalizan el F1. Los fragmentos sin material cantado puntuable se identifican por separado.
- **Fragmentos.** El ensayo rápido extrae 24 s en el 40 % del intervalo admisible de cada mezcla, usando solo su duración. Para puntuar se recortan simétricamente 500 ms de los bordes. Este ensayo usa la transcripción del propio fragmento. Las letras completas recuperadas por título solo pueden corroborarse en las pruebas de grabación completa.
- **Objetivo de aprobación automática.** En una misma muestra evaluable, WER ≤5 %, p90 ≤120 ms, clase correcta ≥90 % y F1 ≥0,85. La comparación humana describe una referencia concreta y una elección de melodía principal. Un dueto, un rap o una voz de acompañamiento pueden admitir varias transcripciones musicalmente razonables. Hacen falta sesiones de canto a ciegas para medir la experiencia real de puntuación.
- **Reproducibilidad.** La matriz macOS procesa cuatro paquetes completos por máquina, con los mismos requisitos fijados y el mismo generador. Cada máquina recupera únicamente los paquetes que necesita y publica las métricas. Los audios, letras y mapas de referencia no se redistribuyen en los resultados. [Ejecución en macOS](https://github.com/AlexAmMo/karaoke/actions/runs/44899035944) · [Evaluador](../../scripts/benchmark_generation_corpus.py) · [Preparación de las ediciones](../../scripts/prepare_generation_validation.py)

Con Python 3.12 en el entorno de generación y FFmpeg en el PATH se pueden reproducir las pruebas. El segundo comando se ejecuta en el entorno de la app, que incluye los lectores del catálogo. Se requiere espacio para pesos e intermedios en el directorio privado elegido.

```sh
uv venv --python 3.12 build/chart-env
uv run --locked python scripts/prepare_generation_validation.py docs/validation/generacion-muestra.json build/private-recordings --language en
uv pip install --python build/chart-env/bin/python -r src/karaoke/generation_assets/requirements.txt
build/chart-env/bin/python scripts/benchmark_generation_corpus.py build/private-recordings/manifest.json build/private-scores --lookup-lyrics
```

La variante adicional de Tune Studio asignó un máximo acústico de comienzo silábico a cada sílaba cercana. Con una ventana de 300 ms, en *Go the Distance* bajó el p90 de 125 a 108 ms y elevó el F1 de 0,582 a 0,607. En *Sigo aquí* elevó el p90 de 139 a 150 ms para una mejora de F1 inferior a 0,002. En Fito pasó de 111 a 122 ms. No se adoptó como ajuste general del generador. En otra prueba se comprobó el perfil estándar con una vocal sintética afinada en la4 e intervalo sordo. Devolvió MIDI 69 y un evento sin puntuación, respectivamente.

Antes de revisar el conjunto retenido se definió una comprobación adicional de confianza para el modo automático. Se considera candidato un mapa con letra independiente corroborada al menos al 90 %, concordancia de clase entre los estimadores musicales de al menos el 88 % y un máximo del 15 % de notas marcadas para revisar. Se comparan por separado su cobertura y cuántos candidatos incumplen realmente alguno de los cuatro objetivos. Se trata de un experimento de calibración. La app requiere aprobación humana en todos los casos.

## Repetibilidad, memoria y corrección de tonos

GAME usa muestreo aleatorio durante la segmentación. Dos generaciones de la misma grabación podían producir barras distintas. Al fijar la semilla en 113 y crear una sesión de segmentación por canción obtuvimos tres huellas idénticas para los eventos de un fragmento real. Una cuarta ejecución con semilla 114 produjo otra huella. La semilla queda en el manifiesto. En el separador se conserva únicamente la salida vocal durante la suma de ventanas. En una mezcla estéreo de 24 s el máximo error absoluto de los 2.116.800 valores de muestra frente a las cuatro salidas de referencia fue cero. En una canción de cuatro minutos esto evita acumular unos 242 MiB de salidas estéreo que se iban a descartar.

Probamos también los pesos MIT de corrección musical de Nico Franke. Calculamos la afinación global del cantante, su distribución tonal en la nota y el contexto de las notas vecinas y del tono de la canción. La regla publicada permite desplazamientos de hasta dos semitonos cuando la probabilidad del modelo supera el umbral de 0,5. Usamos el modelo de alturas. El modelo independiente de finales redujo la cobertura correcta en las tres canciones de ensayo. La reproducción mantiene las duraciones obtenidas de la voz. [Código de los refinadores y características](https://github.com/ZerNico/tunestudio/blob/88d4fac5cb6df35c593cc16e730eddd10d96de39/training/src/tunestudio_training/pipeline/notefix.py) · [Pesos y evaluación del autor](https://huggingface.co/tuneperfect/tunestudio-note-refiners)

| Canción y referencia fijas | Clase antes / después | F1 antes / después | Notas cuyo tono cambió |
|---|---:|---:|---:|
| Sigo aquí | 82,9 % / 83,1 % | 0,554 / 0,551 | 12 |
| Go the Distance | 79,9 % / 80,3 % | 0,582 / 0,604 | 30 |
| Por la boca vive el pez | 70,3 % / 74,3 % | 0,747 / 0,777 | 48 |

Estas comparaciones usaron exactamente los mismos eventos y la misma letra antes y después del corrector. El F1 de *Sigo aquí* bajó dos milésimas mientras subió la clase por fotograma. Los tres ensayos miden el cambio del corrector respecto a su propia entrada.

## Primer conjunto retenido

Antes de fijar la semilla y aplicar el último corrector de tono se evaluaron 20 fragmentos por idioma. Cada uno dura 24 s y empieza en la posición definida por el protocolo. Cada celda es la mediana de la métrica calculada por grabación. El p90 es el p90 de cada fragmento antes de tomar la mediana. [Ejecución en Windows x64](https://github.com/AlexAmMo/karaoke/actions/runs/44899387367)

| Idioma | Grabaciones | WER | Inicio p90 | Clase correcta | F1 de ataques | Pasan todos |
|---|---:|---:|---:|---:|---:|---:|
| Español, M4 | 20 | 6,93 % | 133 ms | 71,75 % | 0,624 | 0 |
| Inglés, Windows x64 | 20 | 6,86 % | 74 ms | 69,52 % | 0,623 | 0 |

El mismo runner de Windows preparó los 79,45 s completos de *Mr. Fancy Pants* en 189 s incluyendo separación, ASR y construcción del mapa. Frente a esa referencia se obtuvo WER del 52,61 %, p90 de 59 ms, clase del 55,38 % y F1 de 0,496. El error pequeño de las palabras acertadas coexistió con muchas palabras ausentes o distintas. Una prueba de doce segundos con el perfil estándar generó asimismo un paquete con 38 notas. Cada ejecución en CI descarga los paquetes oficiales con sus créditos y verifica su identidad. Los trabajos distribuidos almacenan únicamente los resultados numéricos.

### Recuperación de un verso omitido

En la grabación completa de *Mr. Fancy Pants* el primer pase reconoció 104 palabras, frente a las 211 del mapa humano. La letra de LRCLIB describía la misma edición, pero con casi el doble de texto del que recogió Whisper. El generador vuelve a escuchar el audio en ventanas de 24 s con tres segundos de contexto en cada extremo cuando coinciden tres indicios previos. La identidad y la duración de la edición deben encajar, el texto candidato debe tener entre 1,25 y 2,6 veces la longitud del primer pase y debe contener, en orden, al menos el 85 % de lo que ya se oyó. Cada palabra del segundo pase pertenece a la ventana en la que cae su punto medio.

La letra externa se admite únicamente si el segundo pase aporta al menos un 20 % de palabras adicionales, su longitud queda entre 0,88 y 1,13 veces la de ese pase y el acuerdo ordenado supera el 85 %. Los casos que ya tienen una letra corroborada conservan un solo pase. Los casos sin indicios suficientes conservan su transcripción inicial.

| Misma grabación, mismo modelo | Palabras reconocidas | WER de ASR | Acuerdo con la letra recuperada |
|---|---:|---:|---:|
| CPU, pase completo | 104 | 53,08 % | Insuficiente |
| CPU, ventanas de 18 s | 204 | 8,53 % | 96,3 % |
| CPU, ventanas de 24 s | 203 | 6,64 % | 98,0 % |
| Apple Metal, ventanas de 24 s | 203 | 6,16 % | 98,5 % |

La letra recuperada por ambos dispositivos tuvo WER del 6,64 %. El rescate mantiene la condición de borrador. Las palabras que conservan las dos transcripciones no certifican la melodía ni el resto de la letra. Las cifras proceden de un caso seleccionado por el fallo observado en la primera tanda. Deben considerarse una regresión corregida y una prueba de que se puede recuperar un verso omitido.

### Independencia del evaluador

Al preparar el corpus se verifican los paquetes que se usarán como referencia. Al generar solo se entregan audio, idioma, artista, título y, cuando proceda, letra externa corroborada. Para evaluar se guarda primero el borrador, se calcula su SHA-256 y entonces se abre el mapa humano. Como control adicional se prohibió durante la inferencia abrir los dos ficheros de referencia mediante un auditor de acceso de Python. En la primera comparación se usó el mapa real. En la segunda se desplazaron sus notas cinco semitonos. Ambas inferencias generaron las mismas 63 notas y la misma huella `ca26c201a9cc3603325937dd8f665b56ccd3254bbee834cad08e724def8b13bd`. Con el mapa real se obtuvo clase correcta del 74,79 % y F1 de 0,682. Con la referencia alterada se obtuvo 0,61 % y 0,016.

El reloj de transcodificación también se comprobó por separado. Una mezcla real de 24 s se codificó como Opus en WebM y se procesó con el paso a MP3 del generador. Al decodificar a 8 kHz había el mismo número de muestras. En ventanas a los 2, 12 y 20 s la correlación superó 0,999 y el retardo medido fue 0 ms. Esta medición cubre ese flujo de códecs y equipo.

El runner público de GitHub intentó obtener un máster español por el identificador exacto de YouTube. YouTube exigió autenticación de la máquina y el trabajo se detuvo. El corpus español se procesa en el Mac que sí pudo obtener las grabaciones. Se conservan dos comprobaciones de identidad, SHA-256 del archivo y SHA-256 de todas las muestras PCM a 44,1 kHz estéreo de 16 bits. El conjunto público de resultados contiene identificadores, huellas y medidas. [Prueba de origen del runner](https://github.com/AlexAmMo/karaoke/actions/runs/44900526573) · [Resultados por grabación](generacion-resultados.csv)
