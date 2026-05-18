/**
 * Cliente API para configuraciones de acciones administrativas.
 */

import { apiClient } from '@/lib/api';
import type {
  ActionConfig,
  ActionConfigDetail,
  ActionConfigUpload,
  ActionConfigUpdate,
} from '@/types/action-config';

/**
 * Subir una nueva configuración de acciones.
 */
export async function uploadActionConfig(
  organizationId: string,
  data: ActionConfigUpload
): Promise<ActionConfig> {
  const response = await apiClient.post(
    `/organizations/${organizationId}/config`,
    data
  );
  return response.data;
}

/**
 * Obtener la configuración activa de una organización.
 */
export async function getActiveActionConfig(
  organizationId: string
): Promise<ActionConfig | null> {
  try {
    const response = await apiClient.get(
      `/organizations/${organizationId}/config`
    );
    return response.data;
  } catch (error: any) {
    if (error.response?.status === 404) {
      return null;
    }
    throw error;
  }
}

/**
 * Listar todas las configuraciones de una organización.
 */
export async function listActionConfigs(
  organizationId: string
): Promise<ActionConfig[]> {
  const response = await apiClient.get(
    `/organizations/${organizationId}/configs`
  );
  return response.data;
}

/**
 * Obtener detalle completo de una configuración (incluye JSON).
 */
export async function getActionConfigDetail(
  organizationId: string,
  configId: number
): Promise<ActionConfigDetail> {
  const response = await apiClient.get(
    `/organizations/${organizationId}/config/${configId}`
  );
  return response.data;
}

/**
 * Actualizar una configuración (activar/desactivar).
 */
export async function updateActionConfig(
  organizationId: string,
  configId: number,
  data: ActionConfigUpdate
): Promise<ActionConfig> {
  const response = await apiClient.patch(
    `/organizations/${organizationId}/config/${configId}`,
    data
  );
  return response.data;
}

/**
 * Eliminar una configuración.
 */
export async function deleteActionConfig(
  organizationId: string,
  configId: number
): Promise<void> {
  await apiClient.delete(
    `/organizations/${organizationId}/config/${configId}`
  );
}

/**
 * Calcular hash SHA256 de un JSON (primeros 8 caracteres).
 * Debe coincidir con el cálculo del backend.
 */
export async function calculateConfigHash(configJson: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(configJson);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  return hashHex.substring(0, 8);
}

/**
 * Validar que un string sea JSON válido.
 */
export function isValidJson(str: string): boolean {
  try {
    JSON.parse(str);
    return true;
  } catch {
    return false;
  }
}

/**
 * Parsear y validar estructura básica de un archivo .alwaysconfig.
 */
export function validateAlwaysConfig(configJson: string): {
  valid: boolean;
  errors: string[];
} {
  const errors: string[] = [];
  
  if (!isValidJson(configJson)) {
    errors.push('El archivo no es un JSON válido');
    return { valid: false, errors };
  }
  
  try {
    const config = JSON.parse(configJson);
    
    // Validar campos requeridos
    if (!config.version) {
      errors.push('Falta el campo "version"');
    }
    
    if (!config.name) {
      errors.push('Falta el campo "name"');
    }
    
    if (!Array.isArray(config.triggers)) {
      errors.push('El campo "triggers" debe ser un array');
    } else {
      // Validar cada trigger
      config.triggers.forEach((trigger: any, index: number) => {
        if (!trigger.event) {
          errors.push(`Trigger ${index + 1}: falta el campo "event"`);
        }
        
        if (!Array.isArray(trigger.actions)) {
          errors.push(`Trigger ${index + 1}: el campo "actions" debe ser un array`);
        }
      });
    }
    
    return { valid: errors.length === 0, errors };
  } catch (error) {
    errors.push('Error parseando el JSON');
    return { valid: false, errors };
  }
}
