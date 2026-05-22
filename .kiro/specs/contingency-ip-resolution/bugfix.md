# Bugfix Requirements Document

## Introduction

El sistema de contingencia AlwaysPrint tiene bugs relacionados con la activación de contingencia forzada cuando no hay dispositivos activos disponibles, y con la gestión de contingencia a nivel individual vs. VLAN. Hay tres problemas principales:

1. **Template no resuelto en workstation individual**: Cuando se activa contingencia forzada para una workstation individual cuya VLAN no tiene dispositivos activos, el backend envía `printer_ip: null`. El cliente ejecuta el trigger `OnContingencyActivated` sin haber establecido la variable `contingency_printer_ip`, dejando `{{contingency_printer_ip}}` como string literal en la acción `SetTcpPort`.

2. **Botón de contingencia VLAN habilitado sin dispositivos**: El frontend permite activar contingencia a nivel de VLAN aunque no haya dispositivos activos configurados, lo cual no tiene efecto útil.

3. **Falta bloqueo de contingencia individual cuando VLAN está en contingencia**: Cuando una VLAN está en modo contingencia forzada, las workstations individuales de esa VLAN no deberían poder desactivar su contingencia de forma individual — solo se puede quitar a nivel de VLAN.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN forced contingency is activated for an individual workstation AND the VLAN has no active devices AND the workstation has no default_printer_id THEN the system sends a WebSocket message with `printer_ip: null` and the client executes `OnContingencyActivated` with `{{contingency_printer_ip}}` unresolved as a literal string

1.2 WHEN the frontend VLANs page renders the contingency toggle button THEN the system shows the button as enabled for all VLANs regardless of whether they have active devices configured

1.3 WHEN a VLAN has forced contingency active AND a user attempts to deactivate contingency for an individual workstation in that VLAN THEN the system allows the individual deactivation, breaking the VLAN-level contingency intent

1.4 WHEN the backend endpoint `PATCH /workstations/{id}/forced-contingency` is called with `enabled=true` AND no printer_ip can be resolved THEN the system still marks the workstation as `forced_contingency=true` and sends the message with `printer_ip: null`

### Expected Behavior (Correct)

2.1 WHEN forced contingency activation is attempted for an individual workstation AND no printer_ip can be resolved (no default_printer_id and no active devices in VLAN) THEN the system SHALL reject the request with an HTTP 400 error and the client SHALL NOT execute the `OnContingencyActivated` trigger

2.2 WHEN the frontend VLANs page renders the contingency toggle button for a VLAN with no active devices THEN the system SHALL display the button as disabled (visually grayed out) with a tooltip explaining that no contingency device is configured

2.3 WHEN a VLAN has forced contingency active THEN the system SHALL disable the individual contingency toggle button for all workstations in that VLAN in the frontend, preventing individual deactivation (only VLAN-level deactivation is allowed)

2.4 WHEN the client receives a forced contingency activation message (`enabled=true`) with `printer_ip` as null or empty THEN the system SHALL log a warning and refuse to enter contingency mode (not execute `OnContingencyActivated` trigger)

### Unchanged Behavior (Regression Prevention)

3.1 WHEN forced contingency is activated for a workstation AND a valid printer_ip is resolved (from default_printer_id or active device in VLAN) THEN the system SHALL CONTINUE TO send the WebSocket message with the resolved printer_ip and the client SHALL CONTINUE TO execute `OnContingencyActivated` normally

3.2 WHEN forced contingency is deactivated (enabled=false) for any workstation or VLAN THEN the system SHALL CONTINUE TO send the deactivation message and execute `OnContingencyDeactivated` trigger regardless of device availability

3.3 WHEN a VLAN does NOT have forced contingency active THEN the system SHALL CONTINUE TO allow individual workstation contingency toggling as before

3.4 WHEN the frontend VLANs page renders the contingency toggle button for a VLAN with active devices THEN the system SHALL CONTINUE TO display the button as enabled and functional

3.5 WHEN the client receives a forced contingency activation message with a valid non-empty printer_ip THEN the system SHALL CONTINUE TO set the `contingency_printer_ip` config variable and execute the `OnContingencyActivated` trigger normally
