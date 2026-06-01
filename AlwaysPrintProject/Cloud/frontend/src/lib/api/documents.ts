/**
 * Cliente API para documentos del sistema.
 */

import { apiClient } from '@/lib/api';
import type { DocumentInfo, DocumentListResponse, DocumentUpdate } from '@/types/document';

/**
 * Listar documentos con paginación y búsqueda.
 */
export async function listDocuments(params?: {
  page?: number;
  page_size?: number;
  search?: string;
}): Promise<DocumentListResponse> {
  const response = await apiClient.get('/documents/', { params });
  return response.data;
}

/**
 * Obtener un documento por ID.
 */
export async function getDocument(documentId: string): Promise<DocumentInfo> {
  const response = await apiClient.get(`/documents/${documentId}`);
  return response.data;
}

/**
 * Crear un nuevo documento (subir PDF).
 */
export async function createDocument(data: {
  title: string;
  description?: string;
  file: File;
}): Promise<DocumentInfo> {
  const formData = new FormData();
  formData.append('title', data.title);
  if (data.description) {
    formData.append('description', data.description);
  }
  formData.append('file', data.file);

  const response = await apiClient.post('/documents/', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
}

/**
 * Actualizar metadatos de un documento.
 */
export async function updateDocument(
  documentId: string,
  data: DocumentUpdate
): Promise<DocumentInfo> {
  const response = await apiClient.patch(`/documents/${documentId}`, data);
  return response.data;
}

/**
 * Reemplazar el archivo PDF de un documento.
 */
export async function replaceDocumentFile(
  documentId: string,
  file: File
): Promise<DocumentInfo> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await apiClient.put(`/documents/${documentId}/file`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
}

/**
 * Eliminar un documento.
 */
export async function deleteDocument(documentId: string): Promise<void> {
  await apiClient.delete(`/documents/${documentId}`);
}
