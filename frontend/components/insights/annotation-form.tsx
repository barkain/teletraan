'use client';

import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { Loader2, Send, Save } from 'lucide-react';

const MAX_CHARACTERS = 500;

interface AnnotationFormProps {
  /** Initial note value for edit mode */
  initialNote?: string;
  /** Whether the form is in edit mode */
  isEditing?: boolean;
  /** Loading state */
  isLoading?: boolean;
  /** Called when form is submitted */
  onSubmit: (note: string) => void;
  /** Called when cancel is clicked (edit mode only) */
  onCancel?: () => void;
  /** Placeholder text */
  placeholder?: string;
}

export function AnnotationForm({
  initialNote = '',
  isEditing = false,
  isLoading = false,
  onSubmit,
  onCancel,
  placeholder = 'Add a note about this insight...',
}: AnnotationFormProps) {
  const [note, setNote] = useState(initialNote);

  // Reset note when initialNote changes (switching between edit modes)
  useEffect(() => {
    setNote(initialNote);
  }, [initialNote]);

  const charactersRemaining = MAX_CHARACTERS - note.length;
  const isOverLimit = charactersRemaining < 0;
  const isEmpty = note.trim().length === 0;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!isEmpty && !isOverLimit && !isLoading) {
      onSubmit(note.trim());
      if (!isEditing) {
        setNote('');
      }
    }
  };

  const handleCancel = () => {
    setNote(initialNote);
    onCancel?.();
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="relative">
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder={placeholder}
          disabled={isLoading}
          className={cn(
            'w-full min-h-[100px] p-3 rounded-md border bg-background resize-none',
            'placeholder:text-muted-foreground',
            'focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent',
            'disabled:cursor-not-allowed disabled:opacity-50',
            isOverLimit && 'border-destructive focus:ring-destructive'
          )}
          aria-label={isEditing ? 'Edit annotation' : 'New annotation'}
        />
        <div
          className={cn(
            'absolute bottom-2 right-2 text-xs',
            isOverLimit
              ? 'text-destructive'
              : charactersRemaining <= 50
                ? 'text-amber-500'
                : 'text-muted-foreground'
          )}
        >
          {charactersRemaining} characters remaining
        </div>
      </div>

      <div className="flex items-center justify-end gap-2">
        {isEditing && onCancel && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleCancel}
            disabled={isLoading}
          >
            Cancel
          </Button>
        )}
        <Button
          type="submit"
          size="sm"
          disabled={isEmpty || isOverLimit || isLoading}
          className="gap-2"
        >
          {isLoading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              {isEditing ? 'Saving...' : 'Adding...'}
            </>
          ) : isEditing ? (
            <>
              <Save className="h-4 w-4" />
              Save Changes
            </>
          ) : (
            <>
              <Send className="h-4 w-4" />
              Add Annotation
            </>
          )}
        </Button>
      </div>
    </form>
  );
}
