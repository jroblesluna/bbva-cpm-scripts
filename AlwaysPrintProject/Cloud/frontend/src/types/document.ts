/**
 * Tipos para documentos del sistema.
 */

export interface DocumentInfo {
  id: string;
  title: string;
  description: string | null;
  file_name: string;
  file_size: number;
  download_url: string;
  created_by_id: string | null;
  created_by_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentListResponse {
  items: DocumentInfo[];
  total: number;
  page: number;
  page_size: number;
}

export interface DocumentUpdate {
  title?: string;
  description?: string;
}
