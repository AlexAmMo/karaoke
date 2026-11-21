# El silencio digital no se envía al reconocedor

El control técnico de Turbo CPU int8 produjo cinco palabras sobre un WAV de un segundo con todas sus muestras a cero. La observación real y su configuración se conservan en [el ensayo RMS-ASR](research-letras-rms-asr-2026-11-21.md); la transcripción completaba su recorrido, pero esas palabras no tenían apoyo en el audio.

`generation_worker.transcribe` comprueba ahora la entrada vacía y la onda mono remuestreada antes de cargar Whisper. Si todas las muestras son exactamente cero, devuelve una transcripción vacía. El flujo de generación ya convierte la ausencia de palabras en el mensaje «No se reconoció una voz con letra suficiente para generar el mapa». En la recuperación por ventanas se omiten también contextos completamente a cero, conservando los desplazamientos originales de los contextos siguientes.

No se introduce un umbral de volumen: una señal no nula de amplitud `1e-9` sigue llegando intacta al reconocedor. El control se refiere al audio mono que éste recibe; incluye la cancelación exacta de canales al promediar, sin modificar el método de mezcla. No detecta instrumental, ruido de fondo ni silencio acústico aproximado, y no garantiza eliminar otras alucinaciones o mejorar las letras cantadas.

## Validación

Se añadieron cinco regresiones sin modelos ni dispositivos de audio. Cuatro fallaron antes del cambio: entrada vacía, ceros estéreo, canales que se cancelan al mezclar y una ventana inicial silenciosa. El caso de voz muy baja ya pasaba. Tras la corrección pasan las cinco, las quince pruebas de generación seleccionadas y la suite completa de **257 pruebas en 18,94 segundos**, además de Ruff y la comprobación de espacios de Git.

La prueba de ventanas coloca una señal entre los segundos 35 y 36 y comprueba que su palabra conserva esos tiempos después de omitir los contextos silenciosos anterior y posterior. Se utilizan dobles de lectura, remuestreo y reconocimiento para ejecutar esas regresiones en CI sin dependencias del entorno opcional de modelos.

Una comprobación adicional usa el **mismo WAV a cero del control real**, SHA-256 `9645d459db82a31de54ad82e57e839142cf4b038ce0e5b96fa674e33d096f83b`, con SoundFile y SciPy reales. La función devuelve cero palabras sin llamar al reconocedor ni importar Whisper o PyTorch. La evidencia local está en `build/generation-next/silence-guard/real-wav-check.json`. No se vuelve a cargar Turbo para verificar una condición determinista sobre ceros.

La corrección se desarrolló en una copia de trabajo separada mientras continuaba el ensayo comparativo. Las dieciséis condiciones de ese ensayo conservan la implementación anterior firmada; no se mezclan resultados de ambas versiones ni se atribuye a este cambio una mejora de sus métricas.
