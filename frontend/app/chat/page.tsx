import { Metadata } from 'next';
import { ChatContainer } from '@/components/chat/chat-container';

export const metadata: Metadata = {
  title: 'Chat | Market Analyzer',
  description: 'AI-powered market analysis chat interface',
};

export default function ChatPage() {
  return (
    <div className="h-[calc(100vh-4rem-1.5rem)] -m-6">
      <ChatContainer className="h-full" />
    </div>
  );
}
