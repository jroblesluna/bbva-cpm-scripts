/**
 * Tipos TypeScript para configuraciones de acciones administrativas.
 */

export interface ActionConfig {
  id: number;
  organization_id: string;
  name: string;
  version: string;
  description: string | null;
  config_hash: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  created_by_id: string | null;
}

export interface ActionConfigDetail extends ActionConfig {
  config_json: string;
  storage_path: string | null;
}

export interface ActionConfigUpload {
  config_json: string;
  is_active: boolean;
}

export interface ActionConfigUpdate {
  is_active?: boolean;
}

export interface ActionConfigDownloadInfo {
  hash: string;
  download_url: string;
  name: string;
  version: string;
}

export interface ActionConfigSyncStatus {
  workstation_id: string;
  has_config: boolean;
  local_hash: string | null;
  cloud_hash: string | null;
  is_synced: boolean;
}

/**
 * Estructura del archivo .alwaysconfig parseado
 */
export interface AlwaysConfigFile {
  version: string;
  name: string;
  description?: string;
  created_at: string;
  triggers: TriggerConfig[];
}

export interface TriggerConfig {
  event: string;
  description: string;
  actions: ActionConfigItem[];
}

export interface ActionConfigItem {
  type: string;
  description: string;
  parameters?: Record<string, any>;
  store_result_in?: string;
  condition?: ConditionConfig;
  actions?: ActionConfigItem[];
}

export interface ConditionConfig {
  variable: string;
  operator: string;
  value: any;
}

/**
 * Eventos soportados
 */
export const TRIGGER_EVENTS = {
  ON_SERVICE_START: 'OnServiceStart',
  ON_TRAY_LAUNCHED: 'OnTrayLaunched',
  ON_CONFIG_CHANGE: 'OnConfigChange',
  ON_USER_LOGON: 'OnUserLogon',
  ON_USER_LOGOFF: 'OnUserLogoff',
} as const;

/**
 * Tipos de acciones soportadas
 */
export const ACTION_TYPES = {
  PROPAGATE_PERMISSIONS: 'PropagatePermissions',
  GET_LOGGED_IN_USERS: 'GetLoggedInUsers',
  DELETE_FOLDER_CONTENTS: 'DeleteFolderContents',
  STOP_SERVICE: 'StopService',
  START_SERVICE: 'StartService',
  KILL_PROCESSES_BY_NAME: 'KillProcessesByName',
  STOP_TRAY: 'StopTray',
  START_TRAY: 'StartTray',
  CONDITIONAL: 'Conditional',
} as const;
