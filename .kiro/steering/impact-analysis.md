# Análisis de Impacto Antes de Cada Cambio

## Regla Principal

Antes de implementar cualquier cambio (fix, refactor, nueva feature, optimización), detenerte y evaluar si el cambio propuesto anula, debilita o contradice un objetivo ya establecido del sistema. Un fix local nunca debe crear un problema global.

## Checklist Obligatorio

Antes de modificar código, responder mentalmente:

1. **¿Qué garantía existente podría romperse?**
   - Si estoy removiendo una verificación (hash, firma, validación, chequeo de permisos), ¿qué protección pierdo?
   - Si estoy cambiando un flujo de datos, ¿qué componente downstream depende del formato anterior?

2. **¿El cambio es coherente con el propósito del módulo?**
   - Si el propósito de SignatureVerifier es garantizar integridad + autenticidad, cualquier cambio que elimine uno de esos dos pilares es incorrecto.
   - Si el propósito de un endpoint es servir datos firmados, un "workaround" que sirve datos sin firma anula el objetivo.

3. **¿Estoy resolviendo el síntoma o la causa raíz?**
   - Si un hash no coincide entre Python y C#, la causa raíz es la diferencia de serialización, no la verificación del hash. La solución es normalizar la serialización, no eliminar la verificación.
   - Si un componente falla por formato incompatible, la solución es adaptar el formato, no bypassear la validación.

4. **¿El cambio introduce un path sin protección?**
   - Si existe un path "happy" con verificación y un path "fallback" sin ella, un atacante siempre usará el fallback.
   - Los fallbacks deben ser fail-closed (rechazar), no fail-open (aceptar sin validar).

## Principios de Seguridad

- **Nunca eliminar una verificación para resolver un bug de compatibilidad.** Resolver la incompatibilidad manteniendo la verificación.
- **Fail-closed por defecto.** Si no se puede verificar algo → rechazar, no aceptar.
- **Un workaround temporal SIEMPRE debe documentarse como deuda técnica** con un TODO explícito y una explicación de qué protección se perdió.

## Principios de Funcionalidad

- **Si un archivo cambia de formato, TODOS los lectores deben actualizarse.** No solo el principal — también los secundarios (readers de UI, monitores, exportadores).
- **Si un componente shared se modifica, verificar TODOS sus callers.** Un cambio en SignatureVerifier afecta a ActionEngine, ConfigManager, CloudManager y OnDemandConfigReader.
- **Si se cachea un resultado, verificar que la invalidación del caché cubre todos los escenarios** (cambio de config, rotación de cert, reinicio de worker, modificación manual).

## Flujo de Decisión

```
¿El cambio elimina/debilita alguna verificación o protección?
  → SÍ: PARAR. Buscar solución que mantenga la protección.
  → NO: Continuar.

¿El cambio modifica un formato de datos?
  → SÍ: Listar TODOS los componentes que leen/escriben ese formato.
        ¿Se actualizaron todos?
        → NO: Actualizar antes de mergear.
  → NO: Continuar.

¿El cambio afecta un componente compartido (Shared)?
  → SÍ: Listar todos los callers/consumers.
        ¿Alguno se rompe con el cambio?
        → SÍ: Corregir o notificar.
  → NO: Continuar.
```

## Ejemplos de Errores a Evitar

| Síntoma | Fix incorrecto | Fix correcto |
|---------|---------------|--------------|
| Hash mismatch Python↔C# | Eliminar verificación de hash | Normalizar serialización en ambos lados |
| Firma DER no verifica en .NET | Aceptar sin verificar | Convertir DER→IEEE P1363 |
| Archivo con nuevo formato no se lee | Ignorar archivos nuevos | Actualizar el parser del formato |
| Registry write falla desde Tray | Silenciar el error | Mover la escritura al Service (que tiene permisos) |
| Config legacy sin firma | Aceptarlo "por compatibilidad" | Rechazarlo (fail-closed) |
