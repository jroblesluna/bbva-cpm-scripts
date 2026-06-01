'use client';

/**
 * Página de documentación del sistema.
 *
 * - Admin: CRUD completo (crear, ver, editar, eliminar documentos PDF)
 * - Operario: solo ver listado y descargar PDFs
 */

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '@/hooks/useAuth';
import { useTranslations } from 'next-intl';
import {
  FileText,
  Upload,
  Download,
  Trash2,
  Eye,
  Pencil,
  Search,
  LayoutGrid,
  List,
  Plus,
  AlertCircle,
  Calendar,
  User as UserIcon,
  HardDrive,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { useToast } from '@/hooks/use-toast';

import {
  listDocuments,
  createDocument,
  updateDocument,
  deleteDocument,
} from '@/lib/api/documents';
import type { DocumentInfo } from '@/types/document';

function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

export default function DocumentationPage() {
  const { isAdmin } = useAuth();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const t = useTranslations('documentation');
  const tCommon = useTranslations('common');

  // Estado de UI
  const [viewMode, setViewMode] = useState<'cards' | 'table'>('cards');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const pageSize = viewMode === 'cards' ? 10 : 20;

  // Dialogs
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [editingDoc, setEditingDoc] = useState<DocumentInfo | null>(null);

  // Form state para crear
  const [newTitle, setNewTitle] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newFile, setNewFile] = useState<File | null>(null);

  // Form state para editar
  const [editTitle, setEditTitle] = useState('');
  const [editDescription, setEditDescription] = useState('');

  // Query para listar documentos
  const { data, isLoading } = useQuery({
    queryKey: ['documents', page, pageSize, search],
    queryFn: () => listDocuments({ page, page_size: pageSize, search: search || undefined }),
  });

  const documents = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / pageSize);

  // Mutation para crear
  const createMutation = useMutation({
    mutationFn: createDocument,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      toast({ title: t('createSuccess'), description: t('createSuccessDesc') });
      setCreateDialogOpen(false);
      resetCreateForm();
    },
    onError: (error: { detail?: string }) => {
      toast({
        title: t('errorTitle'),
        description: error?.detail || t('errorCreate'),
        variant: 'destructive',
      });
    },
  });

  // Mutation para actualizar
  const updateMutation = useMutation({
    mutationFn: ({ id, data: updateData }: { id: string; data: { title?: string; description?: string } }) =>
      updateDocument(id, updateData),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      toast({ title: t('updateSuccess'), description: t('updateSuccessDesc') });
      setEditDialogOpen(false);
      setEditingDoc(null);
    },
    onError: (error: { detail?: string }) => {
      toast({
        title: t('errorTitle'),
        description: error?.detail || t('errorUpdate'),
        variant: 'destructive',
      });
    },
  });

  // Mutation para eliminar
  const deleteMutation = useMutation({
    mutationFn: deleteDocument,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      toast({ title: t('deleteSuccess'), description: t('deleteSuccessDesc') });
    },
    onError: (error: { detail?: string }) => {
      toast({
        title: t('errorTitle'),
        description: error?.detail || t('errorDelete'),
        variant: 'destructive',
      });
    },
  });

  // Handlers
  const resetCreateForm = () => {
    setNewTitle('');
    setNewDescription('');
    setNewFile(null);
  };

  const handleCreate = () => {
    if (!newTitle.trim() || !newFile) return;
    createMutation.mutate({
      title: newTitle.trim(),
      description: newDescription.trim() || undefined,
      file: newFile,
    });
  };

  const handleEdit = (doc: DocumentInfo) => {
    setEditingDoc(doc);
    setEditTitle(doc.title);
    setEditDescription(doc.description || '');
    setEditDialogOpen(true);
  };

  const handleUpdate = () => {
    if (!editingDoc || !editTitle.trim()) return;
    updateMutation.mutate({
      id: editingDoc.id,
      data: {
        title: editTitle.trim(),
        description: editDescription.trim() || undefined,
      },
    });
  };

  const handleDelete = (doc: DocumentInfo) => {
    if (confirm(t('deleteConfirm', { title: doc.title }))) {
      deleteMutation.mutate(doc.id);
    }
  };

  const handleDownload = (doc: DocumentInfo) => {
    window.open(doc.download_url, '_blank');
  };

  const handleSearch = (value: string) => {
    setSearch(value);
    setPage(1);
  };

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Encabezado */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">{t('title')}</h1>
          <p className="text-muted-foreground mt-1">{t('subtitle')}</p>
        </div>
        {isAdmin() && (
          <Button onClick={() => { setCreateDialogOpen(true); resetCreateForm(); }}>
            <Plus className="mr-2 h-4 w-4" />
            {t('createBtn')}
          </Button>
        )}
      </div>

      {/* Barra de filtros */}
      <Card>
        <CardContent className="p-4">
          <div className="flex flex-col md:flex-row gap-4">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder={t('searchPlaceholder')}
                value={search}
                onChange={(e) => handleSearch(e.target.value)}
                className="pl-9"
              />
            </div>
            <div className="flex items-center gap-1 border rounded-md p-0.5">
              <Button
                variant={viewMode === 'cards' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('cards')}
                className="h-8 w-8 p-0"
                title={t('viewCards')}
              >
                <LayoutGrid className="w-4 h-4" />
              </Button>
              <Button
                variant={viewMode === 'table' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('table')}
                className="h-8 w-8 p-0"
                title={t('viewTable')}
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
      ) : documents.length === 0 ? (
        <Card>
          <CardContent className="py-12">
            <div className="text-center">
              <FileText className="mx-auto h-12 w-12 text-muted-foreground mb-4" />
              <p className="text-muted-foreground">{t('noDocuments')}</p>
              {isAdmin() && (
                <Button
                  variant="outline"
                  className="mt-4"
                  onClick={() => { setCreateDialogOpen(true); resetCreateForm(); }}
                >
                  {t('uploadFirst')}
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      ) : viewMode === 'cards' ? (
        /* Vista de tarjetas */
        <div className="space-y-4">
          {documents.map((doc) => (
            <Card key={doc.id} className="p-4 md:p-6">
              <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3">
                    <FileText className="h-5 w-5 text-red-500 shrink-0" />
                    <h3 className="font-medium truncate">{doc.title}</h3>
                    <Badge variant="secondary" className="shrink-0">PDF</Badge>
                  </div>
                  {doc.description && (
                    <p className="text-sm text-muted-foreground mt-1 ml-8 line-clamp-2">
                      {doc.description}
                    </p>
                  )}
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-gray-600 mt-2 ml-8">
                    <span className="flex items-center gap-1">
                      <HardDrive className="h-3.5 w-3.5" />
                      {formatFileSize(doc.file_size)}
                    </span>
                    <span className="flex items-center gap-1">
                      <Calendar className="h-3.5 w-3.5" />
                      {new Date(doc.created_at).toLocaleDateString()}
                    </span>
                    {doc.created_by_name && (
                      <span className="flex items-center gap-1">
                        <UserIcon className="h-3.5 w-3.5" />
                        {doc.created_by_name}
                      </span>
                    )}
                  </div>
                </div>

                {/* Acciones desktop */}
                <div className="hidden md:flex items-center flex-wrap gap-1">
                  <Button
                    variant="ghost"
                    className="h-8 w-8 p-0"
                    onClick={() => handleDownload(doc)}
                    title={t('download')}
                  >
                    <Download className="h-4 w-4" />
                  </Button>
                  {isAdmin() && (
                    <>
                      <Button
                        variant="ghost"
                        className="h-8 w-8 p-0"
                        onClick={() => handleEdit(doc)}
                        title={tCommon('edit')}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        className="h-8 w-8 p-0"
                        onClick={() => handleDelete(doc)}
                        title={tCommon('delete')}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </>
                  )}
                </div>

                {/* Acciones mobile */}
                <div className="flex md:hidden flex-wrap gap-1 mt-3 pt-3 border-t border-gray-100">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleDownload(doc)}
                  >
                    <Download className="mr-1 h-3.5 w-3.5" />
                    {t('download')}
                  </Button>
                  {isAdmin() && (
                    <>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleEdit(doc)}
                      >
                        <Pencil className="mr-1 h-3.5 w-3.5" />
                        {tCommon('edit')}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleDelete(doc)}
                        className="text-destructive"
                      >
                        <Trash2 className="mr-1 h-3.5 w-3.5" />
                        {tCommon('delete')}
                      </Button>
                    </>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      ) : (
        /* Vista de tabla */
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('columnTitle')}</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('columnSize')}</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('columnDate')}</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('columnAuthor')}</th>
                  <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">{tCommon('actions')}</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {documents.map((doc) => (
                  <tr key={doc.id} className="hover:bg-gray-50">
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-2">
                        <FileText className="h-4 w-4 text-red-500 shrink-0" />
                        <div className="min-w-0">
                          <p className="font-medium truncate">{doc.title}</p>
                          {doc.description && (
                            <p className="text-xs text-muted-foreground truncate max-w-xs">
                              {doc.description}
                            </p>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3 whitespace-nowrap text-muted-foreground">
                      {formatFileSize(doc.file_size)}
                    </td>
                    <td className="px-3 py-3 whitespace-nowrap text-muted-foreground">
                      {new Date(doc.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-3 py-3 whitespace-nowrap text-muted-foreground">
                      {doc.created_by_name || '-'}
                    </td>
                    <td className="px-3 py-3 whitespace-nowrap text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 w-7 p-0"
                          onClick={() => handleDownload(doc)}
                          title={t('download')}
                        >
                          <Download className="h-4 w-4" />
                        </Button>
                        {isAdmin() && (
                          <>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 w-7 p-0"
                              onClick={() => handleEdit(doc)}
                              title={tCommon('edit')}
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 w-7 p-0"
                              onClick={() => handleDelete(doc)}
                              title={tCommon('delete')}
                            >
                              <Trash2 className="h-4 w-4 text-destructive" />
                            </Button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Paginación */}
      {total > pageSize && (
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            {t('pagination', {
              start: (page - 1) * pageSize + 1,
              end: Math.min(page * pageSize, total),
              total,
            })}
          </p>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
            >
              {tCommon('previous')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => setPage(page + 1)}
            >
              {tCommon('next')}
            </Button>
          </div>
        </div>
      )}

      {/* Dialog para crear documento */}
      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t('createTitle')}</DialogTitle>
            <DialogDescription>{t('createDescription')}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div>
              <Label htmlFor="doc-title">{t('fieldTitle')}</Label>
              <Input
                id="doc-title"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder={t('fieldTitlePlaceholder')}
                className="mt-1"
              />
            </div>

            <div>
              <Label htmlFor="doc-description">{t('fieldDescription')}</Label>
              <Textarea
                id="doc-description"
                value={newDescription}
                onChange={(e) => setNewDescription(e.target.value)}
                placeholder={t('fieldDescriptionPlaceholder')}
                className="mt-1"
                rows={3}
              />
            </div>

            <div>
              <Label htmlFor="doc-file">{t('fieldFile')}</Label>
              <input
                id="doc-file"
                type="file"
                accept=".pdf,application/pdf"
                onChange={(e) => setNewFile(e.target.files?.[0] || null)}
                className="mt-1 block w-full text-sm text-muted-foreground
                  file:mr-4 file:py-2 file:px-4
                  file:rounded-md file:border-0
                  file:text-sm file:font-semibold
                  file:bg-primary file:text-primary-foreground
                  hover:file:bg-primary/90"
              />
              <p className="text-xs text-muted-foreground mt-1">{t('fileHint')}</p>
            </div>

            {newFile && (
              <Alert>
                <FileText className="h-4 w-4" />
                <AlertDescription>
                  {newFile.name} ({formatFileSize(newFile.size)})
                </AlertDescription>
              </Alert>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateDialogOpen(false)}>
              {tCommon('cancel')}
            </Button>
            <Button
              onClick={handleCreate}
              disabled={!newTitle.trim() || !newFile || createMutation.isPending}
            >
              {createMutation.isPending ? t('uploading') : t('createBtn')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog para editar documento */}
      <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t('editTitle')}</DialogTitle>
            <DialogDescription>{t('editDescription')}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div>
              <Label htmlFor="edit-title">{t('fieldTitle')}</Label>
              <Input
                id="edit-title"
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                placeholder={t('fieldTitlePlaceholder')}
                className="mt-1"
              />
            </div>

            <div>
              <Label htmlFor="edit-description">{t('fieldDescription')}</Label>
              <Textarea
                id="edit-description"
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
                placeholder={t('fieldDescriptionPlaceholder')}
                className="mt-1"
                rows={3}
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setEditDialogOpen(false)}>
              {tCommon('cancel')}
            </Button>
            <Button
              onClick={handleUpdate}
              disabled={!editTitle.trim() || updateMutation.isPending}
            >
              {updateMutation.isPending ? tCommon('saving') : tCommon('save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
