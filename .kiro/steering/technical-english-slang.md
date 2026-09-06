---
inclusion: always
---

# Slang Técnico en Inglés en las Respuestas

Independientemente del idioma en el que se esté conversando (típicamente español), los términos técnicos deben expresarse con su **slang técnico en inglés** cuando corresponda, especialmente en descripciones que contemplan una explicación compleja. No traducir al español los términos que la comunidad de ingeniería usa habitualmente en inglés.

## Regla

- El cuerpo de la respuesta puede estar en español, pero los **términos técnicos de arte** van en inglés.
- Aplica sobre todo a explicaciones complejas (concurrencia, redes, sistemas distribuidos, bases de datos, seguridad, rendimiento, arquitectura).
- No forzar traducciones que suenan artificiales o que pierden precisión.

## Ejemplos

| NO usar (traducción forzada) | Usar (slang técnico en inglés) |
|---|---|
| condición de carrera | race condition |
| punto muerto / interbloqueo | deadlock |
| tiempo de espera agotado | timeout |
| memoria intermedia | buffer |
| almacenamiento en caché / acierto de caché | cache / cache hit |
| fallo de caché | cache miss |
| retroceso / retirada | fallback |
| contrapresión | backpressure |
| hilo / hilos | thread / threads |
| bloqueo | lock |
| sondeo | polling |
| carga diferida | lazy loading |
| conexión persistente | keep-alive |
| límite de tasa | rate limit |
| tiempo de inactividad | downtime |
| a prueba de fallos (cerrado/abierto) | fail-closed / fail-open |
| inanición del bucle de eventos | event loop starvation |
| agotamiento del pool | pool exhaustion |
| aislamiento por inquilino | tenant isolation |

## Ejemplo de aplicación

- Incorrecto: "el último read salió vacío por una condición de carrera con la escritura".
- Correcto: "el último read salió vacío por una race condition con la escritura".

## Alcance

- Aplica a TODAS las respuestas del asistente, en cualquier idioma de conversación.
- No aplica a texto de UI destinado a usuarios finales (que sigue las reglas de i18n del proyecto), ni al contenido de documentos donde el proyecto exige español (specs), salvo los términos técnicos que ya se usan en inglés por convención.
