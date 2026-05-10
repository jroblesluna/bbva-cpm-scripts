# Solución al Problema de Bcrypt con Contraseñas

## Problema Original

Al intentar crear un usuario con una contraseña de 16 caracteres, se recibía el siguiente error:

```
ValueError: password cannot be longer than 72 bytes, truncate manually if necessary (e.g. my_password[:72])
```

Este error era confuso porque:
- La contraseña tenía solo 16 caracteres (16 bytes en ASCII)
- Bcrypt tiene un límite de 72 bytes
- El error sugería que la contraseña era demasiado larga

## Causa Raíz

El problema no estaba en nuestro código, sino en una **incompatibilidad entre passlib 1.7.4 y bcrypt 5.x**.

Durante la inicialización, passlib intenta detectar un bug conocido de bcrypt ejecutando una prueba interna. Esta prueba usa un string de más de 72 bytes, lo cual:
- Funcionaba en bcrypt 4.x (más permisivo)
- Falla en bcrypt 5.x (más estricto con el límite de 72 bytes)

El error ocurría **antes** de que nuestro código se ejecutara, durante la carga del módulo.

## Solución Implementada

### 1. Downgrade de bcrypt a 4.1.3

```bash
pip install "bcrypt==4.1.3"
```

Esta versión es compatible con passlib 1.7.4 y permite que la inicialización se complete correctamente.

### 2. Pre-hashing con SHA-256

Para evitar problemas futuros con contraseñas largas o caracteres Unicode, implementamos un sistema de **doble hashing**:

```python
import hashlib

def hash_password(password: str) -> str:
    # 1. Pre-hashear con SHA-256 (produce 64 caracteres hex = 32 bytes)
    password_sha256 = hashlib.sha256(password.encode('utf-8')).hexdigest()
    
    # 2. Hashear el SHA-256 con bcrypt
    return pwd_context.hash(password_sha256)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Aplicar el mismo pre-hashing antes de verificar
    password_sha256 = hashlib.sha256(plain_password.encode('utf-8')).hexdigest()
    return pwd_context.verify(password_sha256, hashed_password)
```

**Ventajas de este enfoque:**
- ✅ Soporta contraseñas de cualquier longitud (incluso >72 bytes)
- ✅ Soporta caracteres Unicode sin problemas
- ✅ SHA-256 siempre produce 64 caracteres (32 bytes), muy por debajo del límite de bcrypt
- ✅ Mantiene la seguridad de bcrypt con cost factor 12
- ✅ No hay pérdida de entropía (SHA-256 es criptográficamente seguro)

### 3. Actualización de requirements.txt

```txt
bcrypt==4.1.3  # Versión específica para compatibilidad con passlib 1.7.4
```

## Pruebas Realizadas

Se creó un script de prueba (`test_password_hash.py`) que verifica:

✅ Contraseñas cortas (11 caracteres)
✅ Contraseñas con caracteres especiales (16 caracteres)
✅ Contraseñas de 72 caracteres (límite bcrypt)
✅ Contraseñas de 100 caracteres (>72 bytes)
✅ Contraseñas con Unicode (ñ, acentos)
✅ Contraseñas con emojis (150 bytes)

**Resultado:** Todas las pruebas pasaron correctamente.

## Alternativas Consideradas

### Opción 1: Truncamiento Manual (Descartada)
```python
password_bytes = password.encode('utf-8')
if len(password_bytes) > 72:
    password = password_bytes[:72].decode('utf-8', errors='ignore')
```

**Problemas:**
- Puede cortar en medio de un carácter multi-byte UTF-8
- Pérdida de información si la contraseña es >72 bytes
- No resuelve el problema de inicialización de passlib

### Opción 2: Actualizar passlib (No disponible)
- No hay versión de passlib compatible con bcrypt 5.x
- passlib 1.7.4 es la última versión estable (2020)

### Opción 3: Usar bcrypt directamente sin passlib (Descartada)
- Requeriría reescribir todo el código de autenticación
- Pérdida de funcionalidades de passlib (múltiples esquemas, deprecation, etc.)

## Recomendaciones

1. **Mantener bcrypt==4.1.3** hasta que passlib lance una versión compatible con bcrypt 5.x
2. **Monitorear actualizaciones** de passlib en https://pypi.org/project/passlib/
3. **No modificar** el sistema de doble hashing (SHA-256 + bcrypt) ya que funciona correctamente
4. **Ejecutar test_password_hash.py** después de cualquier actualización de dependencias

## Referencias

- [Bcrypt 72-byte limit](https://security.stackexchange.com/questions/39849/does-bcrypt-have-a-maximum-password-length)
- [Passlib bcrypt handler](https://passlib.readthedocs.io/en/stable/lib/passlib.hash.bcrypt.html)
- [SHA-256 + bcrypt pattern](https://security.stackexchange.com/questions/6623/pre-hash-password-before-applying-bcrypt-to-avoid-restricting-password-length)

---

**Fecha de implementación:** 2026-05-09  
**Autor:** Robles.AI  
**Estado:** ✅ Resuelto y probado
