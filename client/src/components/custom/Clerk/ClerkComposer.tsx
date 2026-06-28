import { useEffect, useRef, useState, forwardRef } from "react";
import { Button } from "@/components/ui/button";
import { Send, Trash2, Mic, Square, Loader2 } from "lucide-react";
import styles from "./ClerkComposer.module.css";
import {
  parseSlash,
  filterSlash,
  ghostCompletion,
  type SlashCommand,
} from "@/lib/clerkComposer";

interface ClerkComposerProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onClear: () => void;
  hasMessages: boolean;
  disabled: boolean;
  voiceSupported: boolean;
  isRecording: boolean;
  isTranscribing: boolean;
  onMicToggle: () => void;
  /** Extra completions to offer first (e.g. the current section's starter). */
  extraGhost?: string[];
}

/**
 * The composer — an auto-growing textarea (Enter sends, Shift+Enter newlines)
 * with two client-side guides: a `/` command index mapped to the Clerk's real
 * tools, and an above-input "Tab to complete" ghost hint drawn from a static
 * corpus (no LLM call, so it never touches the cost budget).
 */
export const ClerkComposer = forwardRef<HTMLTextAreaElement, ClerkComposerProps>(
  function ClerkComposer(
    {
      value,
      onChange,
      onSubmit,
      onClear,
      hasMessages,
      disabled,
      voiceSupported,
      isRecording,
      isTranscribing,
      onMicToggle,
      extraGhost = [],
    },
    ref
  ) {
    const innerRef = useRef<HTMLTextAreaElement | null>(null);
    const setRefs = (el: HTMLTextAreaElement | null) => {
      innerRef.current = el;
      if (typeof ref === "function") ref(el);
      else if (ref) ref.current = el;
    };

    const [sel, setSel] = useState(0);
    const [dismissed, setDismissed] = useState(false);

    const slash = parseSlash(value);
    const filtered = slash.open ? filterSlash(slash.query) : [];
    const slashOpen = slash.open && !dismissed && filtered.length > 0;
    const ghost = slashOpen ? null : ghostCompletion(value, extraGhost);

    // Keep the highlighted slash row in range as the query narrows.
    useEffect(() => {
      setSel(0);
    }, [slash.query, slash.open]);

    // Auto-grow to fit content, capped by the CSS max-height.
    useEffect(() => {
      const el = innerRef.current;
      if (!el) return;
      el.style.height = "auto";
      el.style.height = `${el.scrollHeight}px`;
    }, [value]);

    const runCommand = (c: SlashCommand) => {
      if (c.action === "clear") {
        onClear();
        onChange("");
      } else {
        onChange(c.prompt ?? "");
      }
      setDismissed(false);
      innerRef.current?.focus();
    };

    const acceptGhost = () => {
      if (ghost) onChange(ghost);
      innerRef.current?.focus();
    };

    const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (slashOpen) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setSel((s) => (s + 1) % filtered.length);
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setSel((s) => (s - 1 + filtered.length) % filtered.length);
          return;
        }
        if (e.key === "Enter" || e.key === "Tab") {
          e.preventDefault();
          runCommand(filtered[Math.min(sel, filtered.length - 1)]);
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          setDismissed(true);
          return;
        }
        return;
      }
      // Menu closed.
      if (e.key === "Tab" && ghost) {
        e.preventDefault();
        acceptGhost();
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        onSubmit();
      }
    };

    return (
      <div className={styles.composer}>
        {slashOpen && (
          <div className={styles.menu} role="listbox" aria-label="Commands">
            <div className={styles.menuCap}>Commands</div>
            {filtered.map((c, i) => (
              <button
                key={c.cmd}
                type="button"
                role="option"
                aria-selected={i === sel}
                className={`${styles.item} ${i === sel ? styles.itemSel : ""}`}
                onMouseEnter={() => setSel(i)}
                onClick={() => runCommand(c)}
              >
                <span className={styles.itemCmd}>/{c.cmd}</span>
                <span className={styles.itemLabel}>{c.label}</span>
                <span className={styles.itemHint}>{c.hint}</span>
              </button>
            ))}
          </div>
        )}

        {ghost && (
          <button type="button" className={styles.ghost} onClick={acceptGhost}>
            <span className={styles.ghostText}>
              <span className={styles.ghostDim}>{value.replace(/^\s+/, "")}</span>
              {ghost.slice(value.replace(/^\s+/, "").length)}
            </span>
            <span className={styles.ghostKey}>Tab ⇥</span>
          </button>
        )}

        <div className={styles.row}>
          {hasMessages && (
            <Button
              variant="ghost"
              size="icon"
              onClick={onClear}
              className={styles.clearButton}
              title="Clear chat"
            >
              <Trash2 className={styles.iconSize} />
            </Button>
          )}
          <textarea
            ref={setRefs}
            rows={1}
            className={styles.textarea}
            value={value}
            onChange={(e) => {
              setDismissed(false);
              onChange(e.target.value);
            }}
            onKeyDown={onKeyDown}
            placeholder={
              isRecording ? "Listening… tap to stop" : "Ask about your finances…  ( / for commands )"
            }
            disabled={disabled || isRecording || isTranscribing}
          />
          {voiceSupported && (
            <Button
              variant="ghost"
              size="icon"
              className={styles.iconBtn}
              onClick={onMicToggle}
              disabled={disabled || isTranscribing}
              title={isRecording ? "Stop recording" : "Speak your message"}
              aria-label={isRecording ? "Stop recording" : "Speak your message"}
              aria-pressed={isRecording}
            >
              {isTranscribing ? (
                <Loader2 className={`${styles.iconSize} ${styles.spin}`} />
              ) : isRecording ? (
                <Square className={`${styles.iconSize} ${styles.recordingMic}`} />
              ) : (
                <Mic className={styles.iconSize} />
              )}
            </Button>
          )}
          <Button
            size="icon"
            className={styles.iconBtn}
            onClick={onSubmit}
            disabled={!value.trim() || disabled || isRecording}
          >
            <Send className={styles.iconSize} />
          </Button>
        </div>
      </div>
    );
  }
);
