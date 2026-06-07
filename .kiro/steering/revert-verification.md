# Verificación de Reverts

Cuando realices un revert generando código de reemplazo (str_replace) en vez de usar `git revert`:

1. **Después de hacer los cambios**, ejecuta `git diff <commit_original>..HEAD -- <archivos_revertidos>` para verificar que el resultado sea idéntico al estado previo.
2. Si el diff NO es vacío, corregir las diferencias antes de commitear.
3. Solo confirmar al usuario que el revert es correcto si el diff está vacío.

Esto aplica a cualquier "revert manual" donde se regenera el contenido anterior en vez de usar el comando git revert.
