'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import type { Message, ToolCall, ChatState, SendMessageOptions } from '@/types/chat';

// WebSocket URL - can be configured via environment variable
const WS_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/api/v1/chat';
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

// Reconnection settings
const RECONNECT_INTERVAL = 3000;
const MAX_RECONNECT_ATTEMPTS = 5;

interface WSMessage {
  type: 'ack' | 'text' | 'tool_call' | 'tool_result' | 'done' | 'error';
  message_id?: string;
  content?: string;
  tool_name?: string;
  tool_args?: Record<string, unknown>;
  tool_result?: unknown;
  error?: string;
}

export function useChat() {
  const [state, setState] = useState<ChatState>({
    messages: [],
    isLoading: false,
    error: null,
    isConnected: false,
  });

  // Refs for WebSocket and message tracking
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const connectRef = useRef<(() => void) | undefined>(undefined);
  const currentMessageRef = useRef<{
    id: string;
    content: string;
    toolCalls: ToolCall[];
  } | null>(null);

  // Generate unique message ID
  const generateId = useCallback(() => crypto.randomUUID(), []);

  // Handle incoming WebSocket messages
  const handleWSMessage = useCallback((data: WSMessage) => {
    switch (data.type) {
      case 'ack':
        // Message acknowledged, nothing to do
        break;

      case 'text':
        // Append text content to current assistant message
        if (currentMessageRef.current && data.content) {
          currentMessageRef.current.content += data.content;

          setState(prev => {
            const messages = [...prev.messages];
            const lastMessage = messages[messages.length - 1];

            if (lastMessage?.role === 'assistant' && lastMessage.id === currentMessageRef.current?.id) {
              messages[messages.length - 1] = {
                ...lastMessage,
                content: currentMessageRef.current.content,
              };
            }

            return { ...prev, messages };
          });
        }
        break;

      case 'tool_call':
        // Add tool call to current message
        if (currentMessageRef.current && data.tool_name) {
          const toolCall: ToolCall = {
            id: crypto.randomUUID(),
            name: data.tool_name,
            args: data.tool_args || {},
            status: 'pending',
          };

          currentMessageRef.current.toolCalls.push(toolCall);

          setState(prev => {
            const messages = [...prev.messages];
            const lastMessage = messages[messages.length - 1];

            if (lastMessage?.role === 'assistant' && lastMessage.id === currentMessageRef.current?.id) {
              messages[messages.length - 1] = {
                ...lastMessage,
                toolCalls: [...currentMessageRef.current!.toolCalls],
              };
            }

            return { ...prev, messages };
          });
        }
        break;

      case 'tool_result':
        // Update tool call with result
        if (currentMessageRef.current && data.tool_name) {
          const toolCalls = currentMessageRef.current.toolCalls;
          const toolIndex = toolCalls.findIndex(
            tc => tc.name === data.tool_name && tc.status === 'pending'
          );

          if (toolIndex !== -1) {
            toolCalls[toolIndex] = {
              ...toolCalls[toolIndex],
              result: data.tool_result,
              status: 'complete',
            };

            setState(prev => {
              const messages = [...prev.messages];
              const lastMessage = messages[messages.length - 1];

              if (lastMessage?.role === 'assistant' && lastMessage.id === currentMessageRef.current?.id) {
                messages[messages.length - 1] = {
                  ...lastMessage,
                  toolCalls: [...toolCalls],
                };
              }

              return { ...prev, messages };
            });
          }
        }
        break;

      case 'done':
        // Response complete
        currentMessageRef.current = null;
        setState(prev => ({ ...prev, isLoading: false }));
        break;

      case 'error':
        // Handle error
        console.error('WebSocket error message:', data.error);
        currentMessageRef.current = null;
        setState(prev => ({
          ...prev,
          isLoading: false,
          error: data.error || 'An error occurred',
        }));
        break;
    }
  }, []);

  // Connect to WebSocket
  const connect = useCallback(() => {
    // Don't reconnect if already connected or connecting
    if (wsRef.current?.readyState === WebSocket.OPEN ||
        wsRef.current?.readyState === WebSocket.CONNECTING) {
      return;
    }

    try {
      const ws = new WebSocket(WS_URL);

      ws.onopen = () => {
        console.log('WebSocket connected');
        reconnectAttemptsRef.current = 0;
        setState(prev => ({ ...prev, isConnected: true, error: null }));
      };

      ws.onclose = (event) => {
        console.log('WebSocket closed:', event.code, event.reason);
        setState(prev => ({ ...prev, isConnected: false }));
        wsRef.current = null;

        // Attempt to reconnect if not a normal closure
        if (event.code !== 1000 && reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttemptsRef.current++;
          console.log(`Reconnecting... attempt ${reconnectAttemptsRef.current}`);
          reconnectTimeoutRef.current = setTimeout(() => connectRef.current?.(), RECONNECT_INTERVAL);
        }
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        setState(prev => ({ ...prev, error: 'Connection error' }));
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
    } catch (error) {
      console.error('Failed to create WebSocket:', error);
      setState(prev => ({ ...prev, error: 'Failed to connect' }));
    }
  }, [handleWSMessage]);

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

    setState(prev => ({ ...prev, isConnected: false }));
  }, []);

  // Send a message via WebSocket
  const sendMessage = useCallback(async (options: SendMessageOptions) => {
    const { content } = options;

    if (!content.trim()) return;

    // Add user message immediately
    const userMessage: Message = {
      id: generateId(),
      role: 'user',
      content: content.trim(),
      timestamp: new Date(),
    };

    // Create placeholder for assistant response
    const assistantMessageId = generateId();
    const assistantMessage: Message = {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      toolCalls: [],
    };

    // Initialize current message tracking
    currentMessageRef.current = {
      id: assistantMessageId,
      content: '',
      toolCalls: [],
    };

    setState(prev => ({
      ...prev,
      messages: [...prev.messages, userMessage, assistantMessage],
      isLoading: true,
      error: null,
    }));

    // Send via WebSocket if connected
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        id: userMessage.id,
        message: content.trim(),
      }));
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
        wsRef.current?.send(JSON.stringify({
          id: userMessage.id,
          message: content.trim(),
        }));
      } catch (error) {
        setState(prev => ({
          ...prev,
          isLoading: false,
          error: 'Failed to connect to chat server',
        }));
        currentMessageRef.current = null;
      }
    }

    return assistantMessage;
  }, [generateId, connect]);

  // Clear chat history (local and server)
  const clearHistory = useCallback(async () => {
    setState(prev => ({
      ...prev,
      messages: [],
      error: null,
    }));

    // Also clear on server
    try {
      await fetch(`${API_URL}/chat/clear`, { method: 'POST' });
    } catch (error) {
      console.error('Failed to clear server chat history:', error);
    }
  }, []);

  // Delete a specific message
  const deleteMessage = useCallback((messageId: string) => {
    setState(prev => ({
      ...prev,
      messages: prev.messages.filter(m => m.id !== messageId),
    }));
  }, []);

  // Retry last message
  const retry = useCallback(async () => {
    const lastUserMessage = [...state.messages]
      .reverse()
      .find(m => m.role === 'user');

    if (lastUserMessage) {
      // Remove the last assistant message if it exists
      const messages = state.messages.filter(m => {
        const lastAssistantIdx = state.messages
          .map((msg, idx) => ({ msg, idx }))
          .filter(({ msg }) => msg.role === 'assistant')
          .pop()?.idx;
        return m.role !== 'assistant' || state.messages.indexOf(m) !== lastAssistantIdx;
      });

      setState(prev => ({ ...prev, messages, error: null }));
      await sendMessage({ content: lastUserMessage.content });
    }
  }, [state.messages, sendMessage]);

  // Auto-connect on mount
  useEffect(() => {
    queueMicrotask(() => connect());

    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return {
    ...state,
    sendMessage,
    clearHistory,
    deleteMessage,
    retry,
    connect,
    disconnect,
  };
}
