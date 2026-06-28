import { useState, useRef, useEffect } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useNavigate } from "react-router-dom";
import type { ActionMessage } from "@/types";
import styles from "./ClerkConversation.module.css";
import { useAssistantChat } from "@/hooks/useAssistantChat";
import { useVoiceInput } from "@/hooks/useVoiceInput";
import { ProposalCard } from "@/components/custom/AssistantInterface/ProposalCard";
import { SourcesCitation } from "@/components/custom/AssistantInterface/SourcesCitation";
import BridgeCard from "@/components/custom/BridgeCard/BridgeCard";
import { ClerkPortrait } from "./ClerkPortrait";
import { ClerkComposer } from "./ClerkComposer";
import { ClerkVoice } from "./ClerkVoice";

const STARTERS = [
  "How much have I spent this week?",
  "What's my biggest expense category?",
  "Am I on track with my budgets?",
  "Show me my recent transactions",
  "How does this month compare to last?",
  "What subscriptions am I paying for?",
];

/** The Clerk at work: a thinking portrait + a live "consulting the ledger" line.
 * Shown while the round-trip is in flight; the latest tool note headlines it. */
function ClerkAtWork({ loading, actions }: { loading: boolean; actions: ActionMessage[] }) {
  const latest = actions.length ? actions[actions.length - 1].text : null;
  return (
    <div className={styles.thinking}>
      {loading && (
        <span className={styles.thinkingPortrait}>
          <ClerkPortrait size={30} state="thinking" blink={false} />
        </span>
      )}
      <div className={styles.thinkingBody}>
        <span className={styles.thinkingText}>
          {latest ?? "The Clerk is consulting your ledger"}
          <span className={styles.nib} aria-hidden>
            <span />
            <span />
            <span />
          </span>
        </span>
      </div>
    </div>
  );
}

interface ClerkConversationProps {
  /** Pre-fill the input when the surface opens (from a contextual ticket).
   * Never auto-sent — the user reviews and sends. */
  seedPrompt?: string;
}

/**
 * The Clerk's conversation surface — message transcript as ledger entries,
 * proposal/bridge cards, the "at work" streaming states, voice, and the guided
 * composer. Shared by the floating window and (later) the ⌘K deck over their own
 * {@link useAssistantChat} instance.
 */
export function ClerkConversation({ seedPrompt = "" }: ClerkConversationProps = {}) {
  const navigate = useNavigate();
  const chat = useAssistantChat();
  const [input, setInput] = useState(seedPrompt);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const voice = useVoiceInput();

  // Resolve the message (typed or a starter), clear the box, and send.
  const submit = (override?: string) => {
    const message = (override ?? input).trim();
    if (!message || chat.isLoading) return;
    setInput("");
    void chat.send(message);
  };

  // Finish recording → transcribe → APPEND the text into the editable box for
  // the user to review. Never auto-sent (a mis-hearing is caught before the LLM).
  const handleVoiceStop = async () => {
    const text = await voice.stop();
    if (text) setInput((prev) => (prev ? `${prev} ${text}` : text));
  };

  // Opened from a contextual ticket: focus the box and drop the cursor at the
  // end so the user can finish or edit the pre-filled prompt.
  useEffect(() => {
    if (!seedPrompt) return;
    const el = composerRef.current;
    if (el) {
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const viewport = scrollAreaRef.current?.querySelector(
      "[data-radix-scroll-area-viewport]"
    ) as HTMLElement | null;
    if (viewport) viewport.scrollTop = viewport.scrollHeight;
  }, [chat.messages, chat.isLoading, chat.isStreaming]);

  const isEmpty = chat.messages.length === 0;
  const lastIdx = chat.messages.length - 1;

  return (
    <>
      <ScrollArea ref={scrollAreaRef} className={styles.scroll}>
        {isEmpty ? (
          <div className={styles.empty}>
            <span className={styles.emptyMark}>
              <ClerkPortrait size={58} blink={false} />
            </span>
            <p className={styles.emptyHeading}>Good day. I keep your ledger.</p>
            <p className={styles.emptySub}>
              Ask about your spending, budgets, or goals — or pull a thread below.
            </p>
            <div className={styles.chips}>
              {STARTERS.map((q) => (
                <button
                  key={q}
                  className={styles.chip}
                  onClick={() => submit(q)}
                  disabled={chat.isLoading}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className={styles.stream}>
            {chat.messages.map((message, index) => {
              const clerk = message.role === "assistant";
              const showCaret = clerk && chat.isStreaming && index === lastIdx;
              return (
                <div
                  key={index}
                  className={`${styles.entry} ${
                    clerk ? styles.entryClerk : styles.entryUser
                  } animate-ink-in`}
                >
                  <div
                    className={`${styles.bubble} ${
                      clerk ? styles.bubbleClerk : styles.bubbleUser
                    }`}
                  >
                    {message.content}
                    {showCaret && <span className={styles.caret} aria-hidden />}
                    {clerk && message.sources && (
                      <SourcesCitation sources={message.sources} />
                    )}
                  </div>
                </div>
              );
            })}
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
            {chat.isStreaming && (chat.isLoading || chat.actionMessages.length > 0) && (
              <ClerkAtWork loading={chat.isLoading} actions={chat.actionMessages} />
            )}
          </div>
        )}
      </ScrollArea>

      <div className={styles.actionContainer}>
        {voice.error && (
          <div className={styles.voiceError} role="alert">
            {voice.error}
          </div>
        )}
        {voice.isRecording || voice.isTranscribing ? (
          <ClerkVoice
            stream={voice.stream}
            isTranscribing={voice.isTranscribing}
            onStop={() => void handleVoiceStop()}
            onCancel={voice.cancel}
          />
        ) : (
          <ClerkComposer
            ref={composerRef}
            value={input}
            onChange={setInput}
            onSubmit={() => submit()}
            onClear={() => void chat.clear()}
            hasMessages={!isEmpty}
            disabled={chat.isLoading}
            voiceSupported={voice.supported}
            isRecording={voice.isRecording}
            isTranscribing={voice.isTranscribing}
            onMicToggle={() => void voice.start()}
          />
        )}
      </div>
    </>
  );
}
