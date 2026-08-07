'use client';

/**
 * Página de administración de la Base de Conocimiento.
 *
 * Permite a los administradores gestionar artículos técnicos que se inyectan
 * como contexto en el prompt del LLM durante el análisis de debugging.
 * Funcionalidad: listar, crear, editar, eliminar artículos con editor Markdown y preview.
 */

import { useState, useCallback, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import { useAuth } from '@/hooks/useAuth';
import { organizationsApi } from '@/lib/api';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Plus,
  Pencil,
  Trash2,
  FileText,
  LayoutGrid,
  List,
  Clock,
  Building2,
  Search,
} from 'lucide-react';
import type { Organization } from '@/types/organization';

import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useToast } from '@/hooks/use-toast';

import {
  getKnowledgeArticles,
  getKnowledgeArticle,
  createKnowledgeArticle,
  updateKnowledgeArticle,
  deleteKnowledgeArticle,
} from '@/lib/api/knowledge-articles';
import type {
  KnowledgeArticle,
  KnowledgeArticleListItem,
  KnowledgeArticleCreate,
  KnowledgeArticleUpdate,
} from '@/types/knowledge-article';

// === TIPOS LOCALES ===

interface ArticleFormData {
  title: string;
  description: string;
  content: string;
}

const EMPTY_FORM: ArticleFormData = {
  title: '',
  description: '',
  content: '',
};

// === COMPONENTE PRINCIPAL ===

export default function KnowledgeBasePage() {
  const t = useTranslations('knowledgeBase');
  const tCommon = useTranslations('common');
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const { user, isAdmin } = useAuth();

  // Organización seleccionada: admin puede cambiarla, operador usa la suya fija
  const [selectedOrgId, setSelectedOrgId] = useState<string | null>(
    user?.organization_id ?? null
  );

  // Para admin: cargar lista de organizaciones
  const { data: organizations } = useQuery<Organization[]>({
    queryKey: ['organizations-list'],
    queryFn: () => organizationsApi.list(),
    enabled: isAdmin(),
  });

  // Auto-seleccionar primera org cuando carguen para admin
  useEffect(() => {
    if (isAdmin() && !selectedOrgId && organizations && organizations.length > 0) {
      setSelectedOrgId(organizations[0].id);
    }
  }, [organizations, selectedOrgId]); // eslint-disable-line react-hooks/exhaustive-deps

  // La organización efectiva
  const organizationId = isAdmin() ? (selectedOrgId || undefined) : (user?.organization_id || undefined);

  // Estado de vista
  const [viewMode, setViewMode] = useState<'cards' | 'table'>('cards');

  // Estado de búsqueda por título
  const [searchQuery, setSearchQuery] = useState('');

  // Estado de dialogs
  const [formDialogOpen, setFormDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [editingArticleId, setEditingArticleId] = useState<string | null>(null);
  const [deletingArticle, setDeletingArticle] = useState<KnowledgeArticleListItem | null>(null);

  // Estado del formulario
  const [formData, setFormData] = useState<ArticleFormData>(EMPTY_FORM);

  // === QUERIES ===

  const {
    data: articles,
    isLoading,
  } = useQuery({
    queryKey: ['knowledge-articles', organizationId],
    queryFn: () => getKnowledgeArticles(organizationId),
    enabled: !!organizationId,
  });

  // === MUTATIONS ===

  const createMutation = useMutation({
    mutationFn: (data: KnowledgeArticleCreate) => createKnowledgeArticle(data, organizationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-articles', organizationId] });
      toast({ title: t('created') });
      closeFormDialog();
    },
    onError: () => {
      toast({ title: t('createError'), variant: 'destructive' });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: KnowledgeArticleUpdate }) =>
      updateKnowledgeArticle(id, data, organizationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-articles', organizationId] });
      toast({ title: t('updated') });
      closeFormDialog();
    },
    onError: () => {
      toast({ title: t('updateError'), variant: 'destructive' });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteKnowledgeArticle(id, organizationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-articles', organizationId] });
      toast({ title: t('deleted') });
      setDeleteDialogOpen(false);
      setDeletingArticle(null);
    },
    onError: () => {
      toast({ title: t('deleteError'), variant: 'destructive' });
    },
  });

  // === HANDLERS ===

  const closeFormDialog = useCallback(() => {
    setFormDialogOpen(false);
    setEditingArticleId(null);
    setFormData(EMPTY_FORM);
  }, []);

  const handleCreate = useCallback(() => {
    setEditingArticleId(null);
    setFormData(EMPTY_FORM);
    setFormDialogOpen(true);
  }, []);

  const handleEdit = useCallback(async (article: KnowledgeArticleListItem) => {
    try {
      const full: KnowledgeArticle = await getKnowledgeArticle(article.id, organizationId);
      setEditingArticleId(full.id);
      setFormData({
        title: full.title,
        description: full.description,
        content: full.content,
      });
      setFormDialogOpen(true);
    } catch {
      toast({ title: t('loadError'), variant: 'destructive' });
    }
  }, [t, toast, organizationId]);

  const handleDeleteClick = useCallback((article: KnowledgeArticleListItem) => {
    setDeletingArticle(article);
    setDeleteDialogOpen(true);
  }, []);

  const handleConfirmDelete = useCallback(() => {
    if (deletingArticle) {
      deleteMutation.mutate(deletingArticle.id);
    }
  }, [deletingArticle, deleteMutation]);

  const handleSubmit = useCallback(() => {
    if (editingArticleId) {
      updateMutation.mutate({
        id: editingArticleId,
        data: {
          title: formData.title,
          description: formData.description,
          content: formData.content,
        },
      });
    } else {
      createMutation.mutate({
        title: formData.title,
        description: formData.description,
        content: formData.content,
      });
    }
  }, [editingArticleId, formData, createMutation, updateMutation]);

  const isFormValid =
    formData.title.length >= 3 &&
    formData.title.length <= 200 &&
    formData.description.length >= 10 &&
    formData.description.length <= 500 &&
    formData.content.trim().length > 0;

  const isMutating = createMutation.isPending || updateMutation.isPending;

  const filteredArticles = articles?.filter((article) =>
    article.title.toLowerCase().includes(searchQuery.trim().toLowerCase())
  );

  // === HELPERS ===

  const formatDate = (dateStr: string): string => {
    const date = new Date(dateStr);
    return date.toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  // === RENDER ===

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Encabezado */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">{t('title')}</h1>
          <p className="text-muted-foreground mt-1">{t('subtitle')}</p>
        </div>
        <Button onClick={handleCreate}>
          <Plus className="mr-2 h-4 w-4" />
          {t('createArticle')}
        </Button>
      </div>

      {/* Selector de organización (solo Admin) */}
      {isAdmin() && (
        <Card>
          <CardContent className="py-4">
            <div className="flex items-center gap-3">
              <Building2 className="h-5 w-5 text-muted-foreground shrink-0" />
              <div className="flex items-center gap-3 flex-1">
                <Label htmlFor="kb-org-select" className="shrink-0 font-medium">
                  {tCommon('organization')}:
                </Label>
                <select
                  id="kb-org-select"
                  value={selectedOrgId ?? ''}
                  onChange={(e) => setSelectedOrgId(e.target.value || null)}
                  className="flex-1 max-w-xs px-3 py-1.5 border rounded-md text-sm bg-background"
                >
                  {!organizations || organizations.length === 0 ? (
                    <option value="">{tCommon('loading')}</option>
                  ) : (
                    organizations.map((org) => (
                      <option key={org.id} value={org.id}>
                        {org.name}
                      </option>
                    ))
                  )}
                </select>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Barra de búsqueda */}
      <Card>
        <CardContent className="p-4">
          <div className="flex flex-col md:flex-row gap-4">
            <div className="flex items-center flex-1">
              <Search className="w-5 h-5 text-gray-400 mr-3" />
              <Input
                type="text"
                placeholder={t('searchPlaceholder')}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="flex-1"
              />
            </div>
            <div className="flex items-center gap-1 border rounded-md p-0.5">
              <Button
                variant={viewMode === 'cards' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('cards')}
                className="h-8 w-8 p-0"
                title={tCommon('viewCards')}
              >
                <LayoutGrid className="w-4 h-4" />
              </Button>
              <Button
                variant={viewMode === 'table' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('table')}
                className="h-8 w-8 p-0"
                title={tCommon('viewTable')}
              >
                <List className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Contenido principal */}
      {isLoading ? (
        <p className="text-center text-muted-foreground py-8">{tCommon('loading')}</p>
      ) : !articles || articles.length === 0 ? (
        <Card>
          <CardContent className="text-center py-12">
            <FileText className="mx-auto h-12 w-12 text-muted-foreground mb-4" />
            <p className="text-muted-foreground">{t('noArticles')}</p>
            <Button variant="outline" className="mt-4" onClick={handleCreate}>
              {t('createArticle')}
            </Button>
          </CardContent>
        </Card>
      ) : !filteredArticles || filteredArticles.length === 0 ? (
        <Card>
          <CardContent className="text-center py-12">
            <Search className="mx-auto h-12 w-12 text-muted-foreground mb-4" />
            <p className="text-muted-foreground">{t('noResults')}</p>
          </CardContent>
        </Card>
      ) : viewMode === 'cards' ? (
        <ArticleCardsView
          articles={filteredArticles}
          t={t}
          formatDate={formatDate}
          onEdit={handleEdit}
          onDelete={handleDeleteClick}
        />
      ) : (
        <ArticleTableView
          articles={filteredArticles}
          t={t}
          tCommon={tCommon}
          formatDate={formatDate}
          onEdit={handleEdit}
          onDelete={handleDeleteClick}
        />
      )}

      {/* Dialog crear/editar artículo */}
      <Dialog open={formDialogOpen} onOpenChange={(open) => { if (!open) closeFormDialog(); }}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {editingArticleId ? t('editArticle') : t('createArticle')}
            </DialogTitle>
            <DialogDescription>
              {t('subtitle')}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            {/* Título */}
            <div>
              <Label htmlFor="article-title">{t('articleTitle')}</Label>
              <Input
                id="article-title"
                value={formData.title}
                onChange={(e) => setFormData((prev) => ({ ...prev, title: e.target.value }))}
                placeholder={t('titlePlaceholder')}
                maxLength={200}
                className="mt-1"
              />
              {formData.title.length > 0 && formData.title.length < 3 && (
                <p className="text-xs text-amber-600 mt-1">
                  {t('titleTooShort', { min: 3, count: formData.title.length })}
                </p>
              )}
            </div>

            {/* Descripción */}
            <div>
              <Label htmlFor="article-description">{t('articleDescription')}</Label>
              <Textarea
                id="article-description"
                value={formData.description}
                onChange={(e) => setFormData((prev) => ({ ...prev, description: e.target.value }))}
                placeholder={t('descriptionPlaceholder')}
                maxLength={500}
                className="mt-1"
                rows={3}
              />
              {formData.description.length > 0 && formData.description.length < 10 && (
                <p className="text-xs text-amber-600 mt-1">
                  {t('descriptionTooShort', { min: 10, count: formData.description.length })}
                </p>
              )}
            </div>

            {/* Editor de contenido con tabs */}
            <div>
              <Label>{t('articleContent')}</Label>
              <Tabs defaultValue="editor" className="mt-1">
                <TabsList>
                  <TabsTrigger value="editor">{t('editor')}</TabsTrigger>
                  <TabsTrigger value="preview">{t('preview')}</TabsTrigger>
                </TabsList>
                <TabsContent value="editor">
                  <Textarea
                    value={formData.content}
                    onChange={(e) => setFormData((prev) => ({ ...prev, content: e.target.value }))}
                    placeholder={t('contentPlaceholder')}
                    className="font-mono text-sm min-h-[300px]"
                  />
                </TabsContent>
                <TabsContent value="preview">
                  <div className="min-h-[300px] border rounded-md p-4 prose prose-sm max-w-none dark:prose-invert overflow-y-auto">
                    {formData.content.trim() ? (
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {formData.content}
                      </ReactMarkdown>
                    ) : (
                      <p className="text-muted-foreground italic">
                        {t('contentPlaceholder')}
                      </p>
                    )}
                  </div>
                </TabsContent>
              </Tabs>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={closeFormDialog}>
              {tCommon('cancel')}
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={!isFormValid || isMutating}
            >
              {isMutating
                ? (editingArticleId ? tCommon('updating') : tCommon('creating'))
                : (editingArticleId ? tCommon('update') : tCommon('create'))
              }
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog confirmación de eliminación */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('deleteArticle')}</DialogTitle>
            <DialogDescription>
              {deletingArticle
                ? t('deleteConfirmation', { title: deletingArticle.title })
                : ''
              }
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteDialogOpen(false)}
            >
              {tCommon('cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={handleConfirmDelete}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? tCommon('deleting') : tCommon('delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// === SUB-COMPONENTES ===

interface ArticleCardsViewProps {
  articles: KnowledgeArticleListItem[];
  t: ReturnType<typeof useTranslations>;
  formatDate: (dateStr: string) => string;
  onEdit: (article: KnowledgeArticleListItem) => void;
  onDelete: (article: KnowledgeArticleListItem) => void;
}

function ArticleCardsView({ articles, t, formatDate, onEdit, onDelete }: ArticleCardsViewProps) {
  return (
    <div className="space-y-4">
      {articles.map((article) => (
        <Card key={article.id} className="p-4 md:p-6">
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
            {/* Info principal */}
            <div className="flex-1 min-w-0">
              <h3 className="font-medium text-base truncate">{article.title}</h3>
              <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                {article.description}
              </p>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-gray-600 mt-2">
                <span className="flex items-center gap-1">
                  <Clock className="h-3.5 w-3.5" />
                  {t('lastUpdated', { date: formatDate(article.updated_at) })}
                </span>
              </div>
            </div>

            {/* Acciones desktop */}
            <div className="hidden md:flex items-center flex-wrap gap-1">
              <Button
                variant="ghost"
                className="h-8 w-8 p-0"
                title={t('editArticle')}
                onClick={() => onEdit(article)}
              >
                <Pencil className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                className="h-8 w-8 p-0"
                title={t('deleteArticle')}
                onClick={() => onDelete(article)}
              >
                <Trash2 className="h-4 w-4 text-destructive" />
              </Button>
            </div>
          </div>

          {/* Acciones mobile */}
          <div className="flex md:hidden flex-wrap gap-1 mt-3 pt-3 border-t border-gray-100">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onEdit(article)}
            >
              <Pencil className="h-4 w-4 mr-1" />
              {t('editArticle')}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onDelete(article)}
            >
              <Trash2 className="h-4 w-4 mr-1 text-destructive" />
              {t('deleteArticle')}
            </Button>
          </div>
        </Card>
      ))}
    </div>
  );
}

interface ArticleTableViewProps {
  articles: KnowledgeArticleListItem[];
  t: ReturnType<typeof useTranslations>;
  tCommon: ReturnType<typeof useTranslations>;
  formatDate: (dateStr: string) => string;
  onEdit: (article: KnowledgeArticleListItem) => void;
  onDelete: (article: KnowledgeArticleListItem) => void;
}

function ArticleTableView({ articles, t, tCommon, formatDate, onEdit, onDelete }: ArticleTableViewProps) {
  return (
    <Card className="overflow-hidden">
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('articleTitle')}</TableHead>
              <TableHead>{t('articleDescription')}</TableHead>
              <TableHead>{tCommon('lastUpdated', { time: '' }).replace(': ', '')}</TableHead>
              <TableHead className="text-right">{tCommon('actions')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {articles.map((article) => (
              <TableRow key={article.id}>
                <TableCell className="font-medium max-w-[200px] truncate">
                  {article.title}
                </TableCell>
                <TableCell className="max-w-[300px] truncate text-muted-foreground">
                  {article.description}
                </TableCell>
                <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                  {formatDate(article.updated_at)}
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex items-center justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 w-7 p-0"
                      title={t('editArticle')}
                      onClick={() => onEdit(article)}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 w-7 p-0"
                      title={t('deleteArticle')}
                      onClick={() => onDelete(article)}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </Card>
  );
}
