'use client';

import { useState } from 'react';
import { Pencil, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import type { InsightAnnotation } from '@/types';

interface AnnotationListProps {
  /** List of annotations to display */
  annotations: InsightAnnotation[];
  /** Called when edit button is clicked */
  onEdit: (annotation: InsightAnnotation) => void;
  /** Called when delete is confirmed */
  onDelete: (annotationId: number) => void;
  /** Loading state */
  isLoading?: boolean;
}

function formatTimestamp(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

export function AnnotationList({
  annotations,
  onEdit,
  onDelete,
  isLoading = false,
}: AnnotationListProps) {
  const [deleteTarget, setDeleteTarget] = useState<InsightAnnotation | null>(null);

  const handleDeleteClick = (annotation: InsightAnnotation) => {
    setDeleteTarget(annotation);
  };

  const handleConfirmDelete = () => {
    if (deleteTarget) {
      onDelete(deleteTarget.id);
      setDeleteTarget(null);
    }
  };

  const handleCancelDelete = () => {
    setDeleteTarget(null);
  };

  if (annotations.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        No annotations yet. Add one above to get started.
      </div>
    );
  }

  return (
    <>
      <div className={cn('space-y-4', isLoading && 'opacity-50 pointer-events-none')}>
        {annotations.map((annotation) => (
          <div
            key={annotation.id}
            className="p-4 rounded-lg border bg-card"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <p className="text-sm whitespace-pre-wrap break-words">
                  {annotation.note}
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  {formatTimestamp(annotation.created_at)}
                  {annotation.updated_at && annotation.updated_at !== annotation.created_at && (
                    <span className="ml-2">(edited)</span>
                  )}
                </p>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        onClick={() => onEdit(annotation)}
                        disabled={isLoading}
                        aria-label="Edit annotation"
                      >
                        <Pencil className="size-3.5" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>Edit</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        onClick={() => handleDeleteClick(annotation)}
                        disabled={isLoading}
                        aria-label="Delete annotation"
                        className="text-destructive hover:text-destructive"
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>Delete</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </div>
          </div>
        ))}
      </div>

      <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && handleCancelDelete()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Annotation?</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete this annotation? This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={handleCancelDelete}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleConfirmDelete}>
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
