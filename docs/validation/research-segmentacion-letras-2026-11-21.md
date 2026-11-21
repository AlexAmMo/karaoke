# Segmentación RMS de voces antes del reconocimiento

Se ha preparado y comprobado una implementación propia de cortes acústicos para las mismas cuarenta grabaciones. **No se ha ejecutado ASR, cargado modelos, consultado letras de referencia ni cambiado la generación del producto.** El resultado permite probar después si unos cortes por actividad vocal mejoran al reconocedor existente; todavía no demuestra una mejora de letras ni de tiempos de palabra.

## Fuentes y decisiones previas

El artículo de Syed y colaboradores propone RMS normalizada de la voz separada, umbrales de entrada y salida de 0,1, silencio mínimo de un segundo y fragmentos de hasta treinta segundos. No fija en esa sección el tamaño de ventana, el salto ni nuestros márgenes. Por ello este ensayo **no es una reproducción exacta del artículo**. [Artículo, sección II-F](https://arxiv.org/html/2506.15514v1#S2.SS6)

La implementación de WhisperX aporta un antecedente de corte en un mínimo de la segunda mitad de una ventana máxima. Su método de agrupación puede juntar regiones separadas; aquí se conserva explícitamente cada silencio largo como barrera. Se leyó el código fijado en `8d8e43bf3698dd1df4b011c0f1a8dd1d468ae365`, sin importarlo ni copiarlo. La licencia de esa revisión es **BSD de dos cláusulas**, no MIT. [Binarización y cortes](https://github.com/m-bain/whisperX/blob/8d8e43bf3698dd1df4b011c0f1a8dd1d468ae365/whisperx/vads/pyannote.py) · [Agrupación](https://github.com/m-bain/whisperX/blob/8d8e43bf3698dd1df4b011c0f1a8dd1d468ae365/whisperx/vads/vad.py) · [Licencia](https://github.com/m-bain/whisperX/blob/8d8e43bf3698dd1df4b011c0f1a8dd1d468ae365/LICENSE)

Las siguientes opciones se fijaron antes de calcular los cuarenta cortes, sin consultar referencias humanas:

- Ventana rectangular retrospectiva de 40 ms, salto de 10 ms y frecuencia nativa de 44.100 Hz: 1.764 y 441 muestras. La ventana suaviza ciclos individuales y el salto conserva una resolución de diez milisegundos; no se optimizaron contra palabras conocidas.
- Energía media entre canales, calculada después de elevar cada canal al cuadrado, para evitar cancelación de fases. Acumulación float64 y bloques de cuatro segundos; sólo se conserva una ventana anterior. Antes de la muestra cero se supone energía cero. El último salto parcial termina exactamente en la última muestra.
- Normalización por el máximo de toda la grabación. El cero permanece cero. Un valor igual a 0,1 cuenta como activo. Cada medida posee su intervalo de salto semiabierto.
- Se cierran únicamente huecos internos menores de un segundo. No se elimina actividad breve. Las islas se amplían cien milisegundos a cada lado, limitados por los extremos del archivo. Un silencio de al menos un segundo nunca se vuelve a unir: su zona central, descontados los dos márgenes, permanece excluida.
- Una isla de más de treinta segundos se corta en el mínimo RMS entre los segundos quince y treinta del siguiente tramo. Si varios mínimos empatan se toma el último. Los cortes se expresan en muestras enteras; dos fragmentos consecutivos comparten la misma frontera, sin solapamiento ni margen adicional.
- Se conserva también el complemento excluido, con sus intervalos exactos. «No retenido por esta regla» no significa «sin voz» ni «sin letra». Un canto débil respecto del máximo de su canción puede quedar fuera.

## Identidad, controles y coste medido

El plan se escribió antes del procesamiento. Verifica SHA-256 del máster y de la voz de cada una de las cuarenta identidades y conserva su cadena de procedencia. Reutiliza únicamente identidad, rutas, hashes y reloj del plan previo de consenso: no lee sus referencias, resultados musicales ni letras. Son veinte másteres españoles y veinte ingleses, con 8.321,785 segundos y 2.935.929.128 bytes de voces almacenadas. Los relojes de las voces se contrastan con sus respectivos másteres; no se supone que una voz inglesa tenga el hash de otra separación.

Doce controles sintéticos pasan: silencio total, impulso en primera y última muestra, archivo más corto que la ventana, señal continua de más de un minuto, estéreo en oposición de fase, huecos de 0,99/1/1,01 segundos, invariancia de ganancia, igualdad del umbral, desempate de mínimos con frontera compartida y rechazo de valores no finitos. El RMS por bloques de 73 y 4.000 muestras coincide con una suma directa independiente, con tolerancia de 1e-12. Se comprueba el último salto parcial, la partición exacta entre muestras retenidas y excluidas y que ninguna muestra clasificada activa quede fuera. Esto prueba la geometría del corte; no reconoce sílabas ni garantiza integridad de palabras.

Los cuarenta archivos se procesaron completos, sin faltantes ni energía nula, en **4,157 s**, incluyendo la nueva comprobación de hashes de las voces y la escritura de resultados. El proceso alcanzó **52,547 MiB RSS** según `getrusage`, dentro de la previsión de 64 MiB. El tiempo no incluye la preparación del plan ni corresponde a un reconocimiento de letras. Se mantuvo el Mac silenciado y no se reprodujo audio.

| Cohorte | Grabaciones | Fragmentos | Segundos retenidos | Segundos excluidos |
|---|---:|---:|---:|---:|
| Español | 20 | 281 | 2.966,150 | 1.336,087 |
| Inglés | 20 | 276 | 3.001,671 | 1.017,876 |
| Total | 40 | 557 | 5.967,821 | 2.353,963 |

Se retiene el **71,71 %** de las muestras y se registra como complemento el **28,29 %**. Hay 832.197 medidas RMS, 439 silencios protegidos y 78 cortes impuestos por el límite de duración. De esos 78, **tres caen en energía activa**: se registran como tales, sin presentarlos como fronteras de palabra. El fragmento más largo mide 29,8 s. Todas las muestras activas están cubiertas y cada archivo se descompone exactamente en segmentos y exclusiones sin duplicación.

Una comprobación posterior con biblioteca estándar recorre los artefactos guardados sin llamar al segmentador: valida hashes, las 40 identidades y la partición exacta de 366.990.701 muestras, la cobertura de actividad y el interior de las 439 barreras. Queda en `v1/geometry-audit.json`, sin errores. Un segundo agente revisó estáticamente el arrastre entre bloques, el último salto, la energía multicanal, las barreras y las fronteras enteras sin encontrar defectos; no repitió los controles ni evaluó el corpus.

## Comparación posterior predeclarada

Se mantienen las cuatro identidades de desarrollo ya utilizadas: `bad-bunny-amorfoda`, `fito-paez-11-y-6`, `jonathan-coulton-mr-fancy-pants` y `northern-star`. No son un conjunto reservado. El futuro ensayo será factorial de dos fuentes por dos segmentaciones: mezcla/nativa, mezcla/RMS, voces/nativa y voces/RMS; son dieciséis transcripciones, publicadas todas. En ambos brazos RMS se aplicarán **los mismos cortes derivados de la voz** al reloj original de su respectiva fuente.

Se conserva Whisper Turbo CPU int8 existente, tres hilos, lote uno, beam cinco, idioma fijo, tiempos de palabra, VAD del reconocedor desactivado y condicionamiento por texto anterior desactivado. Se compararán transcripciones acústicas con los mismos parámetros; la base del producto que incluye letras corroboradas se informará por separado. No se escogerán parámetros, canción ni brazo según la letra humana. Sólo tras congelar las dieciséis salidas se abrirán las referencias para evaluar canciones completas, incluidas repeticiones, omisiones y fallos.

Cada fragmento retornará al tiempo absoluto original, sin desplazar ni estirar el reloj. Se conservarán palabras crudas y repeticiones: no habrá deduplicación por texto. Los tiempos que crucen fronteras se marcarán y conservarán para revisión, sin descartar palabras silenciosamente. El ASR y esta composición temporal **no están implementados ni ejecutados por este comando**; requieren el siguiente ensayo coordinado con el único proceso de inferencia del Mac. Los cortes ya preparados del piloto son 7, 14, 3 y 18 respectivamente.

## Reproducción y evidencia

```sh
uv run python scripts/experiments/rms_vad_lyrics.py selftest
uv run python scripts/experiments/rms_vad_lyrics.py plan --output build/generation-next/rms-vad/reproduction
uv run python scripts/experiments/rms_vad_lyrics.py cuts --output build/generation-next/rms-vad/reproduction
```

Las fuentes primarias y sus hashes están en `build/generation-next/rms-vad/sources/sources.json`. El resultado congelado está en `build/generation-next/rms-vad/v1/`: `plan.json`, `source-at-generation.py`, `frozen.json` y, por cada identidad, `rms.npy` y `cuts.json`. Este último contiene actividad cruda, islas cerradas, silencios protegidos, fragmentos, cortes forzados y complemento exacto, todo en muestras del reloj original. El comando rechaza sobrescribir un directorio de plan o una ejecución congelada.

| Artefacto | SHA-256 |
|---|---|
| Implementación y copia de generación | `2248b29d79c36fba9a9e729eb2dce8ea1175fcb25780be20fb1a5ec13cafaebf` |
| Plan previo | `9ada2924a8c7711b04addbc748ed1c96e145663876b23f6c8a32a611dfcbd94e` |
| Resultados congelados | `84044e8ca1c831fcd1d04c2154df044c133dbbe1fc5b1655bc90f7c74211fe28` |
| Manifiesto de fuentes primarias | `a4b9265981d46f5729da806efcc23df2cca2f4b20cb7934e69877a718434ae1c` |

La geometría y el coste permiten avanzar a la comparación acústica, pero la calidad de letra y la pérdida potencial de canto suave siguen sin medirse. No se ha modificado ningún umbral musical, medidor ni comportamiento de producción para dar por superada una prueba.
