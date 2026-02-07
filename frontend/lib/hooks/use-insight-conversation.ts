'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { fetchApi, postApi, putApi, deleteApi } from '@/lib/api';

// ============================================
// Types
// ============================================

export interface InsightConversation {
  id: number;
  deep_insight_id: number;
  title: string;
  status: 'ACTIVE' | 'ARCHIVED' | 'RESOLVED';
  message_count: number;
  modification_count: number;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  summary: string | null;
}

export interface ConversationMessage {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

export interface ModificationProposal {
  field: string;
  old_value: unknown;
  new_value: unknown;
  reasoning: string;
}

export interface ResearchRequest {
  focus_area: string;
  specific_questions: string[];
  related_symbols: string[];
}

export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  modification?: ModificationProposal;
  research?: ResearchRequest;
  isStreaming?: boolean;
};

export interface ConversationWithMessages extends InsightConversation {
  messages: ConversationMessage[];
}

export interface InsightConversationListResponse {
  items: InsightConversation[];
  total: number;
  has_more: boolean;
}

// WebSocket connection states
export type ConnectionState = 'connecting' | 'connected' | 'disconnected' | 'error';

// WebSocket message types from server
interface WSMessage {
  type: 'assistant_chunk' | 'modification_proposal' | 'research_request' | 'done' | 'error' | 'ack';
  content?: string;
  modification?: ModificationProposal;
  research?: ResearchRequest;
  message_id?: string;
  error?: string;
}

// ============================================
// Query Keys
// ============================================

export const insightConversationKeys = {
  all: ['insight-conversations'] as const,
  lists: () => [...insightConversationKeys.all, 'list'] as const,
  list: (insightId: number) => [...insightConversationKeys.lists(), insightId] as const,
  allConversations: () => [...insightConversationKeys.all, 'all-list'] as const,
  details: () => [...insightConversationKeys.all, 'detail'] as const,
  detail: (conversationId: number) => [...insightConversationKeys.details(), conversationId] as const,
};

// ============================================
// API Endpoints
// ============================================

const conversationApi = {
  // List all conversations across all insights
  listAll: (params?: { limit?: number; offset?: number; status?: string }) =>
    fetchApi<InsightConversationListResponse>(
      `/api/v1/conversations${params ? `?${new URLSearchParams(params as Record<string, string>).toString()}` : ''}`
    ),

  // List conversations for an insight
  list: (insightId: number) =>
    fetchApi<InsightConversationListResponse>(`/api/v1/insights/${insightId}/conversations`),

  // Get single conversation with messages
  get: (conversationId: number) =>
    fetchApi<ConversationWithMessages>(`/api/v1/conversations/${conversationId}`),

  // Create new conversation
  create: (insightId: number, title?: string) =>
    postApi<InsightConversation>(`/api/v1/insights/${insightId}/conversations`, { title }),

  // Update conversation (title, status)
  update: (conversationId: number, data: Partial<Pick<InsightConversation, 'title' | 'status'>>) =>
    putApi<InsightConversation>(`/api/v1/conversations/${conversationId}`, data),

  // Delete conversation
  delete: (conversationId: number) =>
    deleteApi<{ message: string }>(`/api/v1/conversations/${conversationId}`),
};

// ============================================
// Hooks
// ============================================

/**
 * Hook for fetching conversations for an insight
 * Provides list, create, and delete operations with React Query caching
 */
export function useInsightConversations(insightId: number | undefined) {
  const queryClient = useQueryClient();

  // Fetch conversations list
  const query = useQuery<InsightConversationListResponse>({
    queryKey: insightConversationKeys.list(insightId!),
    queryFn: () => conversationApi.list(insightId!),
    enabled: !!insightId,
    staleTime: 30 * 1000, // 30 seconds
  });

  // Create new conversation mutation
  const createMutation = useMutation<InsightConversation, Error, { title?: string }>({
    mutationFn: ({ title }) => conversationApi.create(insightId!, title),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: insightConversationKeys.list(insightId!) });
    },
  });

  // Delete conversation mutation
  const deleteMutation = useMutation<{ message: string }, Error, number>({
    mutationFn: (conversationId) => conversationApi.delete(conversationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: insightConversationKeys.list(insightId!) });
    },
  });

  return {
    ...query,
    conversations: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    hasMore: query.data?.has_more ?? false,
    createConversation: createMutation.mutate,
    createConversationAsync: createMutation.mutateAsync,
    isCreating: createMutation.isPending,
    deleteConversation: deleteMutation.mutate,
    deleteConversationAsync: deleteMutation.mutateAsync,
    isDeleting: deleteMutation.isPending,
  };
}

/**
 * Hook for fetching all conversations across all insights
 * Provides pagination and filtering by status
 */
export function useAllConversations(params?: { limit?: number; offset?: number; status?: string }) {
  const query = useQuery<InsightConversationListResponse>({
    queryKey: [...insightConversationKeys.allConversations(), params],
    queryFn: () => conversationApi.listAll(params),
    staleTime: 30 * 1000, // 30 seconds
  });

  return {
    ...query,
    conversations: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    hasMore: query.data?.has_more ?? false,
  };
}

/**
 * Hook for fetching a single conversation with its messages
 * Provides update operations with React Query caching
 */
export function useInsightConversation(conversationId: number | undefined) {
  const queryClient = useQueryClient();

  // Fetch conversation with messages
  const query = useQuery<ConversationWithMessages>({
    queryKey: insightConversationKeys.detail(conversationId!),
    queryFn: () => conversationApi.get(conversationId!),
    enabled: !!conversationId,
    staleTime: 10 * 1000, // 10 seconds
  });

  // Update conversation mutation
  const updateMutation = useMutation<
    InsightConversation,
    Error,
    Partial<Pick<InsightConversation, 'title' | 'status'>>
  >({
    mutationFn: (data) => conversationApi.update(conversationId!, data),
    onSuccess: (updatedConversation) => {
      // Update the detail cache
      queryClient.setQueryData<ConversationWithMessages>(
        insightConversationKeys.detail(conversationId!),
        (old) => (old ? { ...old, ...updatedConversation } : undefined)
      );
      // Invalidate list caches
      queryClient.invalidateQueries({ queryKey: insightConversationKeys.lists() });
    },
  });

  return {
    ...query,
    conversation: query.data,
    messages: query.data?.messages ?? [],
    updateConversation: updateMutation.mutate,
    updateConversationAsync: updateMutation.mutateAsync,
    isUpdating: updateMutation.isPending,
  };
}

// ============================================
// WebSocket Chat Hook
// ============================================

// WebSocket URL configuration
const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';

// Reconnection settings
const RECONNECT_INTERVAL = 3000;
const MAX_RECONNECT_ATTEMPTS = 5;

/**
 * Hook for managing WebSocket chat with an insight conversation
 * Handles real-time messaging, streaming responses, modification proposals, and research requests
 */
export function useInsightChat(conversationId: number | undefined) {
  const queryClient = useQueryClient();

  // State
  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // Refs
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const connectRef = useRef<(() => void) | undefined>(undefined);
  const currentMessageRef = useRef<{
    id: string;
    content: string;
    modification?: ModificationProposal;
    research?: ResearchRequest;
  } | null>(null);

  // Generate unique message ID
  const generateId = useCallback(() => crypto.randomUUID(), []);

  // WebSocket URL for this conversation
  const wsUrl = conversationId
    ? `${WS_BASE_URL}/api/v1/conversations/${conversationId}/chat`
    : null;

  // Handle incoming WebSocket messages
  const handleWSMessage = useCallback((data: WSMessage) => {
    switch (data.type) {
      case 'ack':
        // Message acknowledged
        break;

      case 'assistant_chunk':
        // Append text content to current assistant message
        if (currentMessageRef.current && data.content) {
          currentMessageRef.current.content += data.content;

          setMessages((prev) => {
            const newMessages = [...prev];
            const lastMessage = newMessages[newMessages.length - 1];

            if (
              lastMessage?.role === 'assistant' &&
              lastMessage.id === currentMessageRef.current?.id
            ) {
              newMessages[newMessages.length - 1] = {
                ...lastMessage,
                content: currentMessageRef.current.content,
              };
            }

            return newMessages;
          });
        }
        break;

      case 'modification_proposal':
        // Handle modification proposal
        if (currentMessageRef.current && data.modification) {
          currentMessageRef.current.modification = data.modification;

          setMessages((prev) => {
            const newMessages = [...prev];
            const lastMessage = newMessages[newMessages.length - 1];

            if (
              lastMessage?.role === 'assistant' &&
              lastMessage.id === currentMessageRef.current?.id
            ) {
              newMessages[newMessages.length - 1] = {
                ...lastMessage,
                modification: data.modification,
              };
            }

            return newMessages;
          });
        }
        break;

      case 'research_request':
        // Handle research request
        if (currentMessageRef.current && data.research) {
          currentMessageRef.current.research = data.research;

          setMessages((prev) => {
            const newMessages = [...prev];
            const lastMessage = newMessages[newMessages.length - 1];

            if (
              lastMessage?.role === 'assistant' &&
              lastMessage.id === currentMessageRef.current?.id
            ) {
              newMessages[newMessages.length - 1] = {
                ...lastMessage,
                research: data.research,
              };
            }

            return newMessages;
          });
        }
        break;

      case 'done':
        // Response complete - mark message as no longer streaming
        if (currentMessageRef.current) {
          setMessages((prev) => {
            const newMessages = [...prev];
            const lastMessage = newMessages[newMessages.length - 1];

            if (
              lastMessage?.role === 'assistant' &&
              lastMessage.id === currentMessageRef.current?.id
            ) {
              newMessages[newMessages.length - 1] = {
                ...lastMessage,
                isStreaming: false,
              };
            }

            return newMessages;
          });
        }
        currentMessageRef.current = null;
        setIsLoading(false);

        // Invalidate conversation query to refresh messages from server
        if (conversationId) {
          queryClient.invalidateQueries({
            queryKey: insightConversationKeys.detail(conversationId),
          });
        }
        break;

      case 'error':
        // Handle error
        console.error('WebSocket error message:', data.error);
        currentMessageRef.current = null;
        setIsLoading(false);
        setError(data.error || 'An error occurred');
        break;
    }
  }, [conversationId, queryClient]);

  // Connect to WebSocket
  const connect = useCallback(() => {
    if (!wsUrl) return;

    // Don't reconnect if already connected or connecting
    if (
      wsRef.current?.readyState === WebSocket.OPEN ||
      wsRef.current?.readyState === WebSocket.CONNECTING
    ) {
      return;
    }

    setConnectionState('connecting');

    try {
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log('WebSocket connected to conversation:', conversationId);
        reconnectAttemptsRef.current = 0;
        setConnectionState('connected');
        setError(null);
      };

      ws.onclose = (event) => {
        console.log('WebSocket closed:', event.code, event.reason);
        setConnectionState('disconnected');
        wsRef.current = null;

        // Attempt to reconnect if not a normal closure
        if (event.code !== 1000 && reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttemptsRef.current++;
          console.log(`Reconnecting... attempt ${reconnectAttemptsRef.current}`);
          reconnectTimeoutRef.current = setTimeout(() => connectRef.current?.(), RECONNECT_INTERVAL);
        }
      };

      ws.onerror = (wsError) => {
        console.error('WebSocket error:', wsError);
        setConnectionState('error');
        setError('Connection error');
      };

      ws.onmessage = (event) => {
        try {
          const data: WSMessage = JSON.parse(event.data);
          handleWSMessage(data);
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e);
        }
      };

      wsRef.current = ws;
    } catch (err) {
      console.error('Failed to create WebSocket:', err);
      setConnectionState('error');
      setError('Failed to connect');
    }
  }, [wsUrl, conversationId, handleWSMessage]);

  // Keep connectRef in sync so the reconnect timer can call the latest version
  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  // Disconnect from WebSocket
  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close(1000, 'User disconnected');
      wsRef.current = null;
    }

    setConnectionState('disconnected');
  }, []);

  // Send a message
  const sendMessage = useCallback(
    async (content: string) => {
      if (!content.trim()) return;

      // Add user message immediately
      const userMessage: ChatMessage = {
        id: generateId(),
        role: 'user',
        content: content.trim(),
        timestamp: new Date(),
      };

      // Create placeholder for assistant response
      const assistantMessageId = generateId();
      const assistantMessage: ChatMessage = {
        id: assistantMessageId,
        role: 'assistant',
        content: '',
        timestamp: new Date(),
        isStreaming: true,
      };

      // Initialize current message tracking
      currentMessageRef.current = {
        id: assistantMessageId,
        content: '',
      };

      setMessages((prev) => [...prev, userMessage, assistantMessage]);
      setIsLoading(true);
      setError(null);

      // Send via WebSocket if connected
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({
            id: userMessage.id,
            message: content.trim(),
          })
        );
      } else {
        // Try to connect and send
        connect();

        // Wait for connection and retry
        const waitForConnection = new Promise<void>((resolve, reject) => {
          const timeout = setTimeout(() => reject(new Error('Connection timeout')), 5000);

          const checkConnection = setInterval(() => {
            if (wsRef.current?.readyState === WebSocket.OPEN) {
              clearInterval(checkConnection);
              clearTimeout(timeout);
              resolve();
            }
          }, 100);
        });

        try {
          await waitForConnection;
          wsRef.current?.send(
            JSON.stringify({
              id: userMessage.id,
              message: content.trim(),
            })
          );
        } catch (err) {
          setIsLoading(false);
          setError('Failed to connect to chat server');
          currentMessageRef.current = null;

          // Remove the placeholder assistant message
          setMessages((prev) => prev.filter((m) => m.id !== assistantMessageId));
        }
      }
    },
    [generateId, connect]
  );

  // Clear local messages
  const clearMessages = useCallback(() => {
    setMessages([]);
    setError(null);
  }, []);

  // Load initial messages from conversation
  const loadInitialMessages = useCallback((conversationMessages: ConversationMessage[]) => {
    const chatMessages: ChatMessage[] = conversationMessages.map((msg) => ({
      id: String(msg.id),
      role: msg.role,
      content: msg.content,
      timestamp: new Date(msg.created_at),
    }));
    setMessages(chatMessages);
  }, []);

  // Auto-connect on mount when conversationId is available
  useEffect(() => {
    if (conversationId) {
      connect();
    }

    return () => {
      disconnect();
    };
  }, [conversationId, connect, disconnect]);

  return {
    // Connection state
    connectionState,
    isConnected: connectionState === 'connected',

    // Message state
    messages,
    isLoading,
    error,

    // Actions
    sendMessage,
    clearMessages,
    loadInitialMessages,
    connect,
    disconnect,
  };
}
