/**
 * Cliente API para artículos de conocimiento (Knowledge Base Library).
 *
 * Gestiona el CRUD de artículos y las asociaciones con perfiles de debugging.
 */

import { apiClient } from '@/lib/api';
import type {
  KnowledgeArticle,
  KnowledgeArticleCreate,
  KnowledgeArticleUpdate,
  KnowledgeArticleListItem,
  ProfileArticleAssociation,
} from '@/types/knowledge-article';

// === CRUD DE ARTÍCULOS ===

/**
 * Obtener listado de artículos de conocimiento de la organización.
 */
export async function getKnowledgeArticles(): Promise<KnowledgeArticleListItem[]> {
  const response = await apiClient.get<KnowledgeArticleListItem[]>(
    '/knowledge-articles'
  );
  return response.data;
}

/**
 * Obtener un artículo de conocimiento por su ID (incluye contenido completo).
 */
export async function getKnowledgeArticle(id: string): Promise<KnowledgeArticle> {
  const response = await apiClient.get<KnowledgeArticle>(
    `/knowledge-articles/${id}`
  );
  return response.data;
}

/**
 * Crear un nuevo artículo de conocimiento.
 */
export async function createKnowledgeArticle(
  data: KnowledgeArticleCreate
): Promise<KnowledgeArticle> {
  const response = await apiClient.post<KnowledgeArticle>(
    '/knowledge-articles',
    data
  );
  return response.data;
}

/**
 * Actualizar un artículo de conocimiento existente.
 * Solo se envían los campos proporcionados.
 */
export async function updateKnowledgeArticle(
  id: string,
  data: KnowledgeArticleUpdate
): Promise<KnowledgeArticle> {
  const response = await apiClient.put<KnowledgeArticle>(
    `/knowledge-articles/${id}`,
    data
  );
  return response.data;
}

/**
 * Eliminar un artículo de conocimiento.
 * Elimina también las asociaciones con perfiles (cascade).
 */
export async function deleteKnowledgeArticle(id: string): Promise<void> {
  await apiClient.delete(`/knowledge-articles/${id}`);
}

// === ASOCIACIONES CON PERFILES DE DEBUGGING ===

/**
 * Obtener los artículos asociados a un perfil de debugging.
 */
export async function getProfileArticles(
  profileId: string
): Promise<KnowledgeArticleListItem[]> {
  const response = await apiClient.get<KnowledgeArticleListItem[]>(
    `/debugging-profiles/${profileId}/knowledge-articles`
  );
  return response.data;
}

/**
 * Asociar artículos de conocimiento a un perfil de debugging.
 * Máximo 10 artículos por perfil. Duplicados se ignoran silenciosamente.
 */
export async function associateArticlesToProfile(
  profileId: string,
  articleIds: string[]
): Promise<void> {
  const body: ProfileArticleAssociation = { article_ids: articleIds };
  await apiClient.post(
    `/debugging-profiles/${profileId}/knowledge-articles`,
    body
  );
}

/**
 * Eliminar la asociación de un artículo con un perfil de debugging.
 */
export async function removeArticleFromProfile(
  profileId: string,
  articleId: string
): Promise<void> {
  await apiClient.delete(
    `/debugging-profiles/${profileId}/knowledge-articles/${articleId}`
  );
}
