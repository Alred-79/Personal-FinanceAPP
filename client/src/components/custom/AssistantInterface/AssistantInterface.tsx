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
import {
  MessageCircle,
  Send,
  Trash2,
  Sparkles,
  Mic,
  Square,
  Loader2,
  Lock,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import styles from "./AssistantInterface.module.css";
import { useAssistantChat } from "@/hooks/useAssistantChat";
import { useVoiceInput } from "@/hooks/useVoiceInput";
import { ProposalCard } from "./ProposalCard";
import { SourcesCitation } from "./SourcesCitation";
import BridgeCard from "@/components/custom/BridgeCard/BridgeCard";

const EXAMPLE_QUESTIONS = [
  "How much have I spent this week?",
  "What's my biggest expense category?",
  "Am I on track with my budget?",
  "Show me my recent transactions",
  "How does this month compare to last?",
  "What subscriptions am I paying for?",
];

export function AssistantInterface() {
  const navigate = useNavigate();
  const chat = useAssistantChat();
  const [input, setInput] = useState("");
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const voice = useVoiceInput();

  // Resolve the message (typed or an example chip), clear the box, and send.
  const submit = (override?: string) => {
    const message = (override ?? input).trim();
    if (!message || chat.isLoading) return;
    setInput("");
    void chat.send(message);
  };

  // Toggle the mic: first tap records, second tap stops + transcribes. The
  // transcript is APPENDED into the editable input box for the user to review —
  // it is never auto-sent (a mis-hearing should be caught before it hits the LLM).
  const handleMicToggle = async () => {
    if (voice.isRecording) {
      const text = await voice.stop();
      if (text) setInput((prev) => (prev ? `${prev} ${text}` : text));
    } else {
      await voice.start();
    }
  };

  useEffect(() => {
    const viewport = scrollAreaRef.current?.querySelector(
      "[data-radix-scroll-area-viewport]"
    ) as HTMLElement | null;
    if (viewport) viewport.scrollTop = viewport.scrollHeight;
  }, [chat.messages]);

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const isEmpty = chat.messages.length === 0;

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
      <SheetContent className={`${styles.sheetContent} !bg-background !text-foreground`}>
        <SheetHeader>
          <SheetTitle className={`${styles.sheetTitle} !text-foreground`}>
            <Sparkles className="h-4 w-4 text-gold" />
            <span className="font-display text-lg font-semibold">The Clerk</span>
          </SheetTitle>
          <p className="text-[10px] uppercase tracking-[0.24em] text-muted-foreground">
            At your service
          </p>
          {/* persistent can/can't line — borrow the read-only credibility (§4) */}
          <p className="mt-1.5 flex items-start gap-1.5 text-[11px] leading-snug text-muted-foreground">
            <Lock className="mt-px h-3 w-3 shrink-0 text-gold" aria-hidden />
            <span>
              I can see your transactions and draft actions. I can&rsquo;t move money
              or see full account numbers.
            </span>
          </p>
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
                    onClick={() => submit(q)}
                    disabled={chat.isLoading}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className={styles.messageContainer}>
              {chat.messages.map((message, index) => (
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
                    {message.role === "assistant" && message.sources && (
                      <SourcesCitation sources={message.sources} />
                    )}
                  </div>
                </div>
              ))}
              {chat.proposal && (
                <ProposalCard
                  proposal={chat.proposal}
                  onDismiss={chat.dismissProposal}
                  onView={(id) => navigate(`/forecast?scenario=${id}`)}
                />
              )}
              {chat.bridge && (
                <BridgeCard bridge={chat.bridge} onDismiss={chat.dismissBridge} />
              )}
              {chat.isLoading && (
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
          {chat.actionMessages.length > 0 && (
            <div className={styles.actionText}>
              {chat.actionMessages.map((action) => (
                <div key={action.id} className={styles.actionMessage}>
                  {action.text}
                </div>
              ))}
            </div>
          )}
          {voice.error && (
            <div className={styles.voiceError} role="alert">
              {voice.error}
            </div>
          )}
          <div className={styles.inputContainer}>
            {!isEmpty && (
              <Button
                variant="ghost"
                size="icon"
                onClick={() => void chat.clear()}
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
              placeholder={
                voice.isRecording ? "Listening… tap to stop" : "Ask about your finances…"
              }
              disabled={chat.isLoading || voice.isRecording || voice.isTranscribing}
              className={styles.messageInput}
            />
            {voice.supported && (
              <Button
                variant="ghost"
                size="icon"
                onClick={handleMicToggle}
                disabled={chat.isLoading || voice.isTranscribing}
                title={
                  voice.isRecording ? "Stop recording" : "Speak your message"
                }
                aria-label={
                  voice.isRecording ? "Stop recording" : "Speak your message"
                }
                aria-pressed={voice.isRecording}
              >
                {voice.isTranscribing ? (
                  <Loader2 className={`${styles.iconSize} ${styles.spin}`} />
                ) : voice.isRecording ? (
                  <Square className={`${styles.iconSize} ${styles.recordingMic}`} />
                ) : (
                  <Mic className={styles.iconSize} />
                )}
              </Button>
            )}
            <Button
              size="icon"
              onClick={() => submit()}
              disabled={!input.trim() || chat.isLoading || voice.isRecording}
            >
              <Send className={styles.iconSize} />
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
