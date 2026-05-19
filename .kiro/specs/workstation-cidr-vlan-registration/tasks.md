# Implementation Plan: Workstation CIDR & VLAN Registration

## Overview

Implementación del registro de workstations con CIDR y auto-asignación de VLANs. El plan se divide en: migración de BD, lógica de backend, cliente C#, y mejoras de frontend. Cada paso construye sobre el anterior, terminando con la integración completa.

## Tasks

- [x] 1. Backend: Migración de BD y modelos
  - [x] 1.1 Crear migración Alembic para agregar columnas `cidr` y `tray_version` a tabla `workstations`
    - Crear archivo de migración con `op.add_column('workstations', Column('cidr', String(45), nullable=True))`
    - Crear columna `tray_version` como `String(50), nullable=True`
    - Incluir downgrade para revertir ambas columnas
    - _Requirements: 2.4, 9.3_

  - [x] 1.2 Actualizar modelo SQLAlchemy `Workstation` con campos `cidr` y `tray_version`
    - Agregar `cidr = Column(String(45), nullable=True)` al modelo
    - Agregar `tray_version = Column(String(50), nullable=True)` al modelo
    - Importar desde `app.core.database import Base`
    - _Requirements: 2.1, 2.4_

  - [x] 1.3 Actualizar schema Pydantic `WorkstationRegisterRequest` con validación CIDR
    - Agregar campo `cidr: str` (obligatorio) con `field_validator`
    - Agregar campo `tray_version: Optional[str] = None`
    - Implementar validación con `ipaddress.ip_network(cidr, strict=False)`
    - Validar que prefix length esté en rango 8-30
    - Normalizar CIDR a forma canónica en el validator
    - _Requirements: 2.2, 2.3, 9.1, 9.2, 9.3_

- [x] 2. Backend: Lógica de auto-asignación de VLAN
  - [x] 2.1 Implementar método `detect_or_create_vlan_for_cidr` en WorkstationService
    - Normalizar CIDR con `ipaddress.ip_network(cidr, strict=False)`
    - Buscar VLANs de la organización que contengan el CIDR en `cidr_ranges`
    - Si existe VLAN con ese CIDR, retornar su UUID
    - Si no existe, crear VLAN con nombre `VLAN_{cidr}` y `cidr_ranges=[cidr]`
    - Manejar race condition: si unique constraint falla, reintentar búsqueda
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 5.1_

  - [x] 2.2 Escribir property test para `detect_or_create_vlan_for_cidr`
    - **Property 4: VLAN Assignment Consistency**
    - **Property 5: Registration Idempotence**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4**

  - [x] 2.3 Implementar validación de unicidad de CIDR por organización
    - Antes de agregar un CIDR a una VLAN (endpoint admin), verificar que no exista en otra VLAN de la misma organización
    - Retornar HTTP 409 Conflict si el CIDR ya está asignado a otra VLAN
    - Aplicar misma verificación en auto-creación de VLAN
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 2.4 Escribir property test para unicidad de CIDR
    - **Property 6: CIDR Uniqueness per Organization**
    - **Validates: Requirements 4.1, 4.2**

  - [x] 2.5 Actualizar método `register_workstation` para usar CIDR
    - Recibir parámetros `cidr` y `tray_version`
    - Llamar a `detect_or_create_vlan_for_cidr` con el CIDR normalizado
    - Asignar `vlan_id` resultante a la workstation
    - Guardar `cidr` y `tray_version` en la workstation
    - Si workstation existente cambia de CIDR, re-evaluar VLAN
    - Filtrar siempre por `organization_id` (tenant isolation)
    - _Requirements: 2.4, 2.5, 3.3, 5.1, 5.2_

  - [x] 2.6 Escribir property test para re-asignación de VLAN
    - **Property 8: VLAN Re-assignment on CIDR Change**
    - **Validates: Requirements 2.5**

- [x] 3. Backend: Endpoints HTTP y WebSocket
  - [x] 3.1 Actualizar endpoint POST `/register` para aceptar `cidr` y `tray_version`
    - Pasar `cidr` y `tray_version` del request al servicio
    - Rechazar con 422 si falta `cidr` o formato inválido
    - Mantener backward compatibility: workstations sin CIDR reciben 422
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.2 Actualizar WebSocket handler para procesar `cidr` y `tray_version` en mensaje `register`
    - Extraer `cidr` y `tray_version` del mensaje JSON
    - Validar CIDR antes de procesar (misma lógica que HTTP)
    - Pasar campos al método `register_workstation`
    - _Requirements: 2.1_

  - [x] 3.3 Escribir tests unitarios para validación CIDR en endpoints
    - Test CIDR válido acepta registro
    - Test CIDR inválido retorna 422
    - Test CIDR con prefix fuera de rango 8-30 retorna 422
    - Test normalización (192.168.1.50/24 → 192.168.1.0/24)
    - **Property 2: CIDR Normalization Idempotence**
    - **Property 3: Invalid CIDR Rejection**
    - **Validates: Requirements 2.2, 2.3, 9.1, 9.2, 9.3**

- [x] 4. Checkpoint - Backend completo
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Cliente C#: Detección de CIDR
  - [x] 5.1 Implementar `GetOutboundCIDR()` en NetworkHelper
    - Obtener interfaces de red activas (excluir Loopback y Tunnel)
    - Ordenar por prioridad (Ethernet > WiFi > otros)
    - Para cada interfaz con gateway IPv4, obtener IP y máscara
    - Calcular network address: IP AND SubnetMask (byte a byte)
    - Calcular prefix length contando bits en la máscara
    - Retornar string `"{networkAddress}/{prefixLength}"` o null si no hay interfaz válida
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 5.2 Implementar `GetOutboundSubnetMask()` helper en NetworkHelper
    - Obtener la máscara de subred de la interfaz principal
    - Reutilizar lógica de selección de interfaz de `GetOutboundCIDR`
    - _Requirements: 1.1_

  - [x] 5.3 Escribir property test para cálculo de CIDR
    - **Property 1: CIDR Calculation Correctness**
    - **Validates: Requirements 1.1, 1.2**

- [x] 6. Cliente C#: Registro con CIDR
  - [x] 6.1 Actualizar CloudRegistration para enviar `cidr` y `tray_version` en registro HTTP
    - Llamar a `NetworkHelper.GetOutboundCIDR()` antes de registrar
    - Obtener versión del Tray desde Assembly (`GetTrayVersion()`)
    - Agregar campos `cidr` y `tray_version` al objeto de registro
    - Si CIDR es null, no intentar registro y mostrar error
    - _Requirements: 2.1, 10.1, 10.2_

  - [x] 6.2 Actualizar mensaje WebSocket `register` para incluir `cidr` y `tray_version`
    - Agregar `cidr` y `tray_version` al JSON del mensaje register
    - Mantener misma lógica de retry si CIDR no disponible
    - _Requirements: 2.1_

  - [x] 6.3 Implementar manejo de error cuando CIDR no se puede detectar
    - Si `GetOutboundCIDR()` retorna null, mostrar mensaje de error en Tray
    - No intentar registro sin CIDR
    - Implementar retry periódico de detección de CIDR
    - Usar `AlwaysPrintLogger` para logging de errores
    - _Requirements: 10.1, 10.2, 10.3_

- [x] 7. Checkpoint - Cliente completo
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Frontend: Filtro por VLAN y columna tray_version
  - [x] 8.1 Agregar filtro dropdown de VLAN en página de workstations
    - Mostrar dropdown solo cuando hay organización seleccionada
    - Poblar con VLANs de la organización seleccionada (fetch desde API)
    - Al seleccionar VLAN, filtrar workstations por `vlan_id`
    - Sin filtro seleccionado, mostrar todas las workstations
    - Usar componentes shadcn/ui existentes
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 8.2 Agregar columna `tray_version` al listado de workstations
    - Agregar columna en la tabla de workstations
    - Mostrar "—" cuando `tray_version` es null
    - Actualizar tipo TypeScript `Workstation` con campo `tray_version`
    - _Requirements: 7.1, 7.2_

  - [x] 8.3 Escribir property test para filtro de VLAN
    - **Property 10: VLAN Filter Correctness**
    - **Validates: Requirements 6.2**

- [x] 9. Frontend: Badges de salud CIDR en VLANs
  - [x] 9.1 Implementar componente `CidrHealthBadge` en página de VLANs
    - Badge verde cuando VLAN tiene exactamente 1 CIDR
    - Badge amarillo cuando VLAN tiene exactamente 2 CIDRs
    - Badge rojo cuando VLAN tiene 3 o más CIDRs
    - Usar clases Tailwind para colores (bg-green-100, bg-yellow-100, bg-red-100)
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x] 9.2 Escribir property test para badge de salud CIDR
    - **Property 9: CIDR Health Badge Mapping**
    - **Validates: Requirements 8.2, 8.3, 8.4**

  - [x] 9.3 Reorganizar detalles de workstation para mejor visibilidad
    - Mostrar CIDR en los detalles de la workstation
    - Mostrar VLAN asignada en los detalles
    - Mostrar tray_version de forma prominente
    - _Requirements: 7.1_

- [x] 10. Frontend: Tenant isolation en queries
  - [x] 10.1 Verificar que todas las queries de VLANs filtran por `organization_id`
    - Endpoint de listado de VLANs filtra por organización
    - Dropdown de filtro solo muestra VLANs de la organización seleccionada
    - _Requirements: 5.2, 5.3_

  - [x] 10.2 Escribir property test para tenant isolation
    - **Property 7: Tenant Isolation**
    - **Validates: Requirements 5.1, 5.2, 5.3**

- [x] 11. Final checkpoint - Integración completa
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido
- Cada task referencia requirements específicos para trazabilidad
- Los checkpoints aseguran validación incremental
- Property tests validan propiedades universales de correctness
- Unit tests validan ejemplos específicos y edge cases
- Importar Base siempre desde `app.core.database` (no `app.db`)
- Todos los textos, comentarios y logs deben estar en español
- Usar `AlwaysPrintLogger` en el cliente C# (no Console.WriteLine)
- Filtrar siempre por `organization_id` en queries del backend (tenant isolation)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["2.1", "5.1", "5.2"] },
    { "id": 3, "tasks": ["2.2", "2.3", "5.3"] },
    { "id": 4, "tasks": ["2.4", "2.5"] },
    { "id": 5, "tasks": ["2.6", "3.1", "3.2"] },
    { "id": 6, "tasks": ["3.3", "6.1", "6.2", "6.3"] },
    { "id": 7, "tasks": ["8.1", "8.2", "9.1"] },
    { "id": 8, "tasks": ["8.3", "9.2", "9.3", "10.1"] },
    { "id": 9, "tasks": ["10.2"] }
  ]
}
```
