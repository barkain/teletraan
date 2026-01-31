// Chat-related types for the LLM interface

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  result?: unknown;
  status: 'pending' | 'complete' | 'error';
  error?: string;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  toolCalls?: ToolCall[];
}

export interface ChatState {
  messages: Message[];
  isLoading: boolean;
  error: string | null;
  isConnected: boolean;
}

export interface SendMessageOptions {
  content: string;
  context?: {
    symbol?: string;
    insightId?: string;
  };
}

// WebSocket message types for future integration
export interface WSMessage {
  type: 'message' | 'tool_call' | 'tool_result' | 'error' | 'ping' | 'pong';
  payload: unknown;
  timestamp: string;
}

export interface WSChatMessage extends WSMessage {
  type: 'message';
  payload: {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    delta?: boolean; // For streaming responses
  };
}

export interface WSToolCallMessage extends WSMessage {
  type: 'tool_call';
  payload: {
    callId: string;
    messageId: string;
    name: string;
    args: Record<string, unknown>;
  };
}

export interface WSToolResultMessage extends WSMessage {
  type: 'tool_result';
  payload: {
    callId: string;
    messageId: string;
    result: unknown;
    error?: string;
  };
}
