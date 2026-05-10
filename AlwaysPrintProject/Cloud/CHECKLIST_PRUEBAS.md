# ✅ Checklist de Pruebas - AlwaysPrint Cloud Manager

## Verificación Rápida del Sistema

**Fecha:** 2026-05-10  
**Objetivo:** Verificar que todas las funcionalidades están operativas

---

## Pre-requisitos

- [ ] Backend corriendo en http://localhost:8000
- [ ] Frontend corriendo en http://localhost:3000
- [ ] Conda environment "alwaysprint" activado
- [ ] Base de datos con migraciones aplicadas

---

## 1. Autenticación y Navegación

### Login
- [ ] Abrir http://localhost:3000
- [ ] Redirige automáticamente a `/login`
- [ ] Logo AlwaysPrint visible
- [ ] Formulario de login presente
- [ ] Ingresar: antonio@robles.ai / admin123
- [ ] Login exitoso
- [ ] Redirige a `/dashboard`

### Navegación
- [ ] Sidebar visible en desktop
- [ ] Logo en sidebar
- [ ] Menú hamburguesa en móvil
- [ ] Usuario "Antonio Robles" visible
- [ ] Badge "Administrador" visible
- [ ] Todos los enlaces del menú funcionan

---

## 2. Dashboard Principal

### Estadísticas
- [ ] 4 tarjetas de estadísticas visibles
- [ ] Estaciones Totales: 0
- [ ] Estaciones Online: 0
- [ ] Contingencia Activa: 0
- [ ] IPs Pendientes: 0 (o número correcto)

### Enlaces Rápidos
- [ ] "Gestionar Estaciones" funciona
- [ ] "Gestionar VLANs" funciona
- [ ] "IPs Pendientes" funciona (si hay pendientes)

---

## 3. Gestión de Organizaciones

### Crear Organización
- [ ] Click en "Organizaciones" en menú
- [ ] Página carga correctamente
- [ ] Click en "Crear Organización"
- [ ] Modal se abre
- [ ] Llenar formulario:
  - Nombre: BBVA
  - Descripción: Banco BBVA - Oficinas Perú
  - Timezone: America/Lima
  - Estado: Activa ✓
- [ ] Click en "Crear"
- [ ] Organización creada exitosamente
- [ ] Aparece en la lista

### Verificar Organización
- [ ] Nombre "BBVA" visible
- [ ] Timezone "America/Lima" visible
- [ ] Badge "Activa" verde
- [ ] Botones "Editar" y "Eliminar" presentes

---

## 4. Gestión de Usuarios

### Crear Usuario Operador
- [ ] Click en "Usuarios" en menú
- [ ] Página carga correctamente
- [ ] Click en "Crear Usuario"
- [ ] Modal se abre
- [ ] Llenar formulario:
  - Nombre: Juan Pérez
  - Email: juan.perez@bbva.com
  - Password: operador123
  - Rol: Operador
  - Organización: BBVA
  - Timezone: (vacío, hereda)
  - Estado: Activo ✓
- [ ] Click en "Crear"
- [ ] Usuario creado exitosamente
- [ ] Aparece en la lista

### Verificar Usuario
- [ ] Nombre "Juan Pérez" visible
- [ ] Email visible
- [ ] Organización "BBVA" visible
- [ ] Rol "Operador" visible
- [ ] Timezone heredado de BBVA

---

## 5. Gestión de VLANs (NUEVO)

### Crear VLAN
- [ ] Click en "VLANs" en menú
- [ ] Página carga correctamente
- [ ] 3 tarjetas de estadísticas visibles
- [ ] Click en "Crear VLAN"
- [ ] Modal se abre
- [ ] Llenar formulario:
  - Nombre: VLAN Oficina Principal
  - Descripción: Red principal de oficinas
  - Rango CIDR: 192.168.1.0/24
- [ ] Click en "Agregar rango"
- [ ] Agregar segundo rango: 10.0.0.0/16
- [ ] Click en "Crear VLAN"
- [ ] VLAN creada exitosamente
- [ ] Aparece en la lista

### Verificar VLAN
- [ ] Nombre visible
- [ ] Descripción visible
- [ ] 2 badges con rangos CIDR
- [ ] Fecha de creación con timezone
- [ ] Botones "Editar" y "Eliminar"

### Editar VLAN
- [ ] Click en "Editar"
- [ ] Modal se abre con datos actuales
- [ ] Cambiar descripción
- [ ] Click en "Actualizar"
- [ ] Cambios guardados
- [ ] Lista se actualiza

### Buscar VLAN
- [ ] Escribir en búsqueda: "Oficina"
- [ ] VLAN se filtra correctamente
- [ ] Limpiar búsqueda
- [ ] Todas las VLANs visibles

---

## 6. Configuración Global (NUEVO)

### Crear Configuración
- [ ] Click en "Configuración" en menú
- [ ] Página carga correctamente
- [ ] Alerta de jerarquía visible
- [ ] Llenar formulario:
  - Cola Corporativa: LexmarkBBVA
  - Intervalo Polling: 5
  - Dominios Bootstrap: bbva.com,bbva.local
  - IP Búsqueda: 192.168.1.100
  - Rango Búsqueda: 192.168.1.0/24
- [ ] Click en "Agregar IP"
- [ ] Agregar segunda IP: 192.168.2.100
- [ ] Click en "Guardar Cambios"
- [ ] Configuración guardada exitosamente

### Verificar Configuración
- [ ] Valores guardados correctamente
- [ ] Información de última actualización visible
- [ ] Botón "Descartar" deshabilitado (sin cambios)

### Modificar Configuración
- [ ] Cambiar intervalo de polling a 10
- [ ] Botón "Descartar" se habilita
- [ ] Botón "Guardar Cambios" se habilita
- [ ] Click en "Descartar"
- [ ] Valor vuelve a 5
- [ ] Cambiar nuevamente a 10
- [ ] Click en "Guardar Cambios"
- [ ] Cambio guardado

---

## 7. Sistema de Mensajes (NUEVO)

### Enviar Mensaje a Organización
- [ ] Click en "Mensajes" en menú
- [ ] Página carga correctamente
- [ ] 4 tarjetas de estadísticas visibles
- [ ] Click en "Enviar Mensaje"
- [ ] Modal se abre
- [ ] Seleccionar: "Toda la organización"
- [ ] Escribir mensaje: "Mensaje de prueba del sistema"
- [ ] Contador de caracteres funciona
- [ ] Click en "Enviar Mensaje"
- [ ] Mensaje enviado exitosamente
- [ ] Aparece en la lista

### Verificar Mensaje
- [ ] Badge "Organización" verde
- [ ] Contenido visible
- [ ] Badge "Pendiente" amarillo (sin workstations aún)
- [ ] Fecha de envío con timezone
- [ ] Fecha de entrega: "-"

### Filtrar Mensajes
- [ ] Filtro por estado: "Pendientes"
- [ ] Mensaje visible
- [ ] Filtro por estado: "Entregados"
- [ ] Sin mensajes (correcto)
- [ ] Filtro por tipo: "Organización"
- [ ] Mensaje visible

### Buscar Mensaje
- [ ] Escribir en búsqueda: "prueba"
- [ ] Mensaje se filtra correctamente
- [ ] Limpiar búsqueda
- [ ] Todos los mensajes visibles

---

## 8. Auditoría (NUEVO)

### Verificar Logs
- [ ] Click en "Auditoría" en menú
- [ ] Página carga correctamente
- [ ] 4 tarjetas de estadísticas visibles
- [ ] Distribución por tipo de acción visible
- [ ] Lista de logs presente

### Verificar Acciones Registradas
- [ ] Log de creación de organización
- [ ] Log de creación de usuario
- [ ] Log de creación de VLAN
- [ ] Log de creación de configuración
- [ ] Log de envío de mensaje
- [ ] Todas con badges de colores correctos

### Filtrar Logs
- [ ] Filtro por tipo: "Crear"
- [ ] Solo logs de creación visibles
- [ ] Filtro por tipo: "Actualizar"
- [ ] Solo logs de actualización visibles
- [ ] Filtro por entidad: "vlan"
- [ ] Solo logs de VLANs visibles

### Buscar en Logs
- [ ] Escribir en búsqueda: "BBVA"
- [ ] Logs se filtran correctamente
- [ ] Limpiar búsqueda
- [ ] Todos los logs visibles

---

## 9. Gestión de Workstations

### Verificar Página
- [ ] Click en "Estaciones" en menú
- [ ] Página carga correctamente
- [ ] 4 tarjetas de estadísticas (todas en 0)
- [ ] Mensaje "No hay workstations"
- [ ] Filtros disponibles

**Nota:** Las workstations aparecerán cuando el cliente Windows se conecte.

---

## 10. IPs Pendientes

### Verificar Página
- [ ] Click en "IPs Pendientes" en menú
- [ ] Página carga correctamente
- [ ] 3 tarjetas de estadísticas
- [ ] Mensaje "No hay IPs pendientes" (si no hay)

**Nota:** Las IPs pendientes aparecerán cuando un cliente intente conectarse desde una IP no autorizada.

---

## 11. Timezone

### Verificar Formateo
- [ ] Ir a "Usuarios"
- [ ] Columna "Creado" muestra formato: `yyyy-MM-dd HH:mm:ss UTC±X`
- [ ] Timezone correcto según usuario

### Cambiar Timezone
- [ ] Click en "Usuarios"
- [ ] Editar tu usuario (Antonio Robles)
- [ ] Cambiar timezone a "America/New_York"
- [ ] Click en "Actualizar"
- [ ] Página se recarga automáticamente
- [ ] Todas las fechas actualizadas al nuevo timezone

---

## 12. Permisos de Operador

### Cerrar Sesión
- [ ] Click en "Cerrar sesión"
- [ ] Redirige a `/login`

### Login como Operador
- [ ] Ingresar: juan.perez@bbva.com / operador123
- [ ] Login exitoso
- [ ] Badge "Operador" visible

### Verificar Menú Limitado
- [ ] Menú NO muestra "Organizaciones"
- [ ] Menú NO muestra "Usuarios"
- [ ] Menú NO muestra "IPs Pendientes"
- [ ] Menú SÍ muestra: Dashboard, Estaciones, VLANs, Configuración, Mensajes, Auditoría

### Verificar Datos Filtrados
- [ ] Dashboard muestra solo datos de BBVA
- [ ] Estaciones muestra solo de BBVA
- [ ] VLANs muestra solo de BBVA
- [ ] Mensajes muestra solo de BBVA
- [ ] Auditoría muestra solo de BBVA

---

## 13. Responsividad

### Desktop
- [ ] Sidebar fijo visible
- [ ] Logo en sidebar
- [ ] Navegación completa
- [ ] Tablas con scroll horizontal si necesario

### Tablet
- [ ] Sidebar se oculta
- [ ] Menú hamburguesa visible
- [ ] Logo en header
- [ ] Tarjetas se adaptan

### Móvil
- [ ] Menú hamburguesa funciona
- [ ] Sidebar se abre/cierra
- [ ] Tablas scrolleables
- [ ] Botones accesibles
- [ ] Formularios usables

---

## 14. API Documentation

### Swagger UI
- [ ] Abrir http://localhost:8000/docs
- [ ] Documentación carga correctamente
- [ ] Todos los endpoints visibles
- [ ] Schemas documentados

### ReDoc
- [ ] Abrir http://localhost:8000/redoc
- [ ] Documentación alternativa carga
- [ ] Navegación funciona

---

## 15. Errores y Validaciones

### Validaciones de Formularios
- [ ] Intentar crear organización sin nombre → Error
- [ ] Intentar crear usuario sin email → Error
- [ ] Intentar crear VLAN sin CIDR → Error
- [ ] Intentar guardar config sin cola → Error
- [ ] Intentar enviar mensaje vacío → Error

### Manejo de Errores
- [ ] Error de red muestra mensaje claro
- [ ] Error de autenticación redirige a login
- [ ] Error de permisos muestra mensaje
- [ ] Loading states visibles durante operaciones

---

## Resumen de Verificación

### Páginas Verificadas
- [ ] Login
- [ ] Dashboard
- [ ] Organizaciones
- [ ] Usuarios
- [ ] Workstations
- [ ] VLANs (NUEVO)
- [ ] Configuración (NUEVO)
- [ ] Mensajes (NUEVO)
- [ ] Auditoría (NUEVO)
- [ ] IPs Pendientes

### Funcionalidades Verificadas
- [ ] Autenticación
- [ ] Navegación
- [ ] CRUD de organizaciones
- [ ] CRUD de usuarios
- [ ] CRUD de VLANs
- [ ] Configuración global
- [ ] Envío de mensajes
- [ ] Auditoría de acciones
- [ ] Sistema de timezone
- [ ] Permisos por rol
- [ ] Búsqueda y filtros
- [ ] Responsividad

---

## Problemas Encontrados

**Registrar aquí cualquier problema:**

1. _____________________________________
2. _____________________________________
3. _____________________________________

---

## Notas Adicionales

**Observaciones:**

_____________________________________
_____________________________________
_____________________________________

---

## Estado Final

- [ ] ✅ Todas las pruebas pasaron
- [ ] ⚠️ Algunas pruebas fallaron (ver "Problemas Encontrados")
- [ ] ❌ Muchas pruebas fallaron (requiere revisión)

---

## Próximo Paso

Una vez completado este checklist:

1. Si todo funciona → Proceder con pruebas de cliente Windows
2. Si hay problemas → Reportar y corregir
3. Si todo está OK → Preparar para despliegue

---

**Fecha de prueba:** _______________  
**Probado por:** _______________  
**Resultado:** _______________

---

© 2026 Inversiones On Line SAC - Robles.AI
