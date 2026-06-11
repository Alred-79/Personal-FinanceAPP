import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { MessageCircle, Send, Trash2, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";
import styles from "./AssistantInterface.module.css";
import { Message, ActionMessage } from "@/types";
import { apiBase } from "@/lib/apiBase";

const EXAMPLE_QUESTIONS = [
  "How much have I spent this week?",
  "What's my biggest expense category?",
  "Am I on track with my budget?",
  "Show me my recent transactions",
  "How does this month compare to last?",
  "What subscriptions am I paying for?",
];

async function refreshAuth(): Promise<boolean> {
  try {
    const res = await fetch(`${apiBase}/refresh/`, {
      method: "POST",
      credentials: "include",
    });
    return res.ok;
  } catch {
    return false;
  }
}

export function AssistantInterface() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [actionMessages, setActionMessages] = useState<ActionMessage[]>([]);
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const viewport = scrollAreaRef.current?.querySelector(
      "[data-radix-scroll-area-viewport]"
    ) as HTMLElement | null;
    if (viewport) viewport.scrollTop = viewport.scrollHeight;
  }, [messages]);

  useEffect(() => {
    const interval = setInterval(() => {
      const now = Date.now();
      setActionMessages((prev) =>
        prev.filter((msg) => now - msg.timestamp < 5000)
      );
    }, 1000);

    return () => clearInterval(interval);
  }, []);

  const handleSend = async (overrideMessage?: string) => {
    const userMessage = (overrideMessage ?? input).trim();
    if (!userMessage || isLoading) return;

    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMessage }]);
    setIsLoading(true);
    setActionMessages([]);

    const chatUrl = `${apiBase}/assistant/chat/?message=${encodeURIComponent(userMessage)}`;

    const doFetch = () =>
      fetch(chatUrl, {
        method: "POST",
        credentials: "include",
      });

    try {
      let response = await doFetch();

      if (response.status === 401) {
        const refreshed = await refreshAuth();
        if (!refreshed) {
          navigate("/login");
          return;
        }
        response = await doFetch();
      }

      if (!response.ok) {
        throw new Error("Failed to send message");
      }

      const reader = response.body?.getReader();
      if (!reader) return;

      const decoder = new TextDecoder();
      let buffer = "";
      let assistantMessage = "";
      let assistantStarted = false;

      const handleFrame = (frame: string) => {
        let eventType = "message";
        let dataStr = "";
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) eventType = line.slice(6).trim();
          else if (line.startsWith("data:")) dataStr += line.slice(5).trim();
        }
        if (!dataStr) return;

        let data: unknown;
        try {
          data = JSON.parse(dataStr);
        } catch {
          return;
        }

        if (eventType === "tool") {
          const { text } = data as { text: string };
          setActionMessages((prev) => [
            ...prev,
            { id: Date.now(), text, timestamp: Date.now() },
          ]);
        } else if (eventType === "token") {
          assistantMessage += data as string;
          if (!assistantStarted) {
            assistantStarted = true;
            setIsLoading(false);
          }
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last?.role === "assistant") {
              last.content = assistantMessage;
              return next;
            }
            return [...next, { role: "assistant", content: assistantMessage }];
          });
        } else if (eventType === "done") {
          setIsLoading(false);
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        let idx: number;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          if (frame.trim()) handleFrame(frame);
        }
      }
      setIsLoading(false);
    } catch (error) {
      console.error("Error sending message:", error);
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleClear = async () => {
    const clearUrl = `${apiBase}/assistant/clear/`;
    const doFetch = () =>
      fetch(clearUrl, { method: "POST", credentials: "include" });

    try {
      let response = await doFetch();

      if (response.status === 401) {
        const refreshed = await refreshAuth();
        if (!refreshed) {
          navigate("/login");
          return;
        }
        response = await doFetch();
      }

      if (!response.ok) throw new Error("Failed to clear chat history");

      setMessages([]);
    } catch (error) {
      console.error("Error clearing chat:", error);
    }
  };

  const isEmpty = messages.length === 0;

  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button
          className={`${styles.assistantButton} assistant-button`}
          size="icon"
        >
          <MessageCircle className="h-6 w-6" />
        </Button>
      </SheetTrigger>
      <SheetContent className={styles.sheetContent}>
        <SheetHeader>
          <SheetTitle className={styles.sheetTitle}>
            <Sparkles className="h-4 w-4" />
            AI Assistant
          </SheetTitle>
        </SheetHeader>

        <ScrollArea ref={scrollAreaRef} className={styles.scrollArea}>
          {isEmpty ? (
            <div className={styles.emptyState}>
              <div className={styles.emptyIcon}>
                <Sparkles className="h-7 w-7" />
              </div>
              <p className={styles.emptyHeading}>What can I help with?</p>
              <p className={styles.emptySubtext}>
                Ask anything about your finances, spending, or budgets.
              </p>
              <div className={styles.exampleGrid}>
                {EXAMPLE_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    className={styles.exampleChip}
                    onClick={() => handleSend(q)}
                    disabled={isLoading}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className={styles.messageContainer}>
              {messages.map((message, index) => (
                <div
                  key={index}
                  className={`${styles.messageWrapper} ${
                    message.role === "assistant" ? "justify-start" : "justify-end"
                  }`}
                >
                  <div
                    className={`${styles.message} ${
                      message.role === "assistant"
                        ? styles.assistantMessage
                        : styles.userMessage
                    }`}
                  >
                    {message.content}
                  </div>
                </div>
              ))}
              {isLoading && (
                <div className={styles.loadingMessage}>
                  <div className={styles.loadingBubble}>
                    <span className={styles.loadingDot} />
                    <span className={styles.loadingDot} />
                    <span className={styles.loadingDot} />
                  </div>
                </div>
              )}
            </div>
          )}
        </ScrollArea>

        <div className={styles.actionContainer}>
          {actionMessages.length > 0 && (
            <div className={styles.actionText}>
              {actionMessages.map((action) => (
                <div key={action.id} className={styles.actionMessage}>
                  {action.text}
                </div>
              ))}
            </div>
          )}
          <div className={styles.inputContainer}>
            {!isEmpty && (
              <Button
                variant="ghost"
                size="icon"
                onClick={handleClear}
                className={styles.clearButton}
                title="Clear chat"
              >
                <Trash2 className={styles.iconSize} />
              </Button>
            )}
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyPress}
              placeholder="Ask about your finances…"
              disabled={isLoading}
              className={styles.messageInput}
            />
            <Button
              size="icon"
              onClick={() => handleSend()}
              disabled={!input.trim() || isLoading}
            >
              <Send className={styles.iconSize} />
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
