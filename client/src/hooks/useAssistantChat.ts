import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Message, ActionMessage, AssistantProposal, AssistantBridge, AssistantSources } from "@/types";
import { apiBase } from "@/lib/apiBase";
import { refreshOnce } from "@/lib/api";

/** Refresh via the SHARED single-flight refresh (F1), so the SSE path and the
 * axios interceptor never issue two concurrent POST /refresh/. Returns whether
 * the refresh succeeded (this hook decides the redirect itself). */
async function refreshAuth(): Promise<boolean> {
  try {
    await refreshOnce();
    return true;
  } catch {
    return false;
  }
}

export interface AssistantChat {
  messages: Message[];
  /** True from send() until the first token lands — the "thinking" window. */
  isLoading: boolean;
  /** True for the whole round-trip (thinking + token streaming) until `done`. */
  isStreaming: boolean;
  /** Transient "the clerk is doing X" notes; self-expire after ~5s. */
  actionMessages: ActionMessage[];
  /** A pending what-if commit offer (propose→confirm via ConfirmCard). */
  proposal: AssistantProposal | null;
  /** A pending Assisted Action Bridge offer (BridgeCard). */
  bridge: AssistantBridge | null;
  send: (message: string) => Promise<void>;
  clear: () => Promise<void>;
  dismissProposal: () => void;
  dismissBridge: () => void;
}

/**
 * The Clerk's chat engine, lifted out of {@link AssistantInterface} so more than
 * one surface can drive it. It owns the SSE round-trip to `/assistant/chat/`
 * (401→refresh→retry), the `\n\n`-framed event parsing (tool / proposal /
 * assisted_action / token / sources / crisis / dispute / tax_resource / done), and the
 * resulting transcript + proposal/bridge state. The propose→confirm cards live
 * in the VIEW layer (so their testids and DOM are owned there); this hook only
 * surfaces the `proposal` / `bridge` payloads.
 *
 * Each call site gets its own instance — the server keeps the authoritative
 * history, so the floating Sheet and the Command Deck simply render their own
 * local view of the conversation without a shared mount lifecycle.
 */
export function useAssistantChat(): AssistantChat {
  const navigate = useNavigate();
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [actionMessages, setActionMessages] = useState<ActionMessage[]>([]);
  const [proposal, setProposal] = useState<AssistantProposal | null>(null);
  const [bridge, setBridge] = useState<AssistantBridge | null>(null);
  // A ref guard so a second send() can't interleave with an in-flight stream
  // regardless of how the caller debounces (state alone is stale in closures).
  const busyRef = useRef(false);
  // F3 — the in-flight stream's AbortController, so unmount cancels the fetch +
  // reader loop instead of leaking them (and setState-after-unmount warnings).
  const abortRef = useRef<AbortController | null>(null);

  // Action notes are ephemeral — drop each one ~5s after it lands.
  useEffect(() => {
    const interval = setInterval(() => {
      const now = Date.now();
      setActionMessages((prev) => prev.filter((msg) => now - msg.timestamp < 5000));
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  // F3 — on unmount, abort any in-flight stream so the reader loop bails and no
  // state update fires after teardown.
  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const send = useCallback(
    async (raw: string) => {
      const userMessage = raw.trim();
      if (!userMessage || busyRef.current) return;
      busyRef.current = true;

      setMessages((prev) => [...prev, { role: "user", content: userMessage }]);
      setIsLoading(true);
      setIsStreaming(true);
      setActionMessages([]);
      setProposal(null);

      const controller = new AbortController();
      abortRef.current = controller;
      const chatUrl = `${apiBase}/assistant/chat/?message=${encodeURIComponent(userMessage)}`;
      const doFetch = () =>
        fetch(chatUrl, {
          method: "POST",
          credentials: "include",
          signal: controller.signal,
        });

      try {
        let response = await doFetch();
        if (response.status === 401) {
          const refreshed = await refreshAuth();
          if (!refreshed) {
            navigate("/login");
            return;
          }
          // Retry the stream AT MOST ONCE after a successful refresh.
          response = await doFetch();
        }
        if (!response.ok) throw new Error("Failed to send message");

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
          } else if (eventType === "proposal") {
            setProposal(data as AssistantProposal);
            setIsLoading(false);
          } else if (eventType === "assisted_action") {
            setBridge(data as AssistantBridge);
            setIsLoading(false);
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
          } else if (eventType === "sources") {
            // W2 — cite-sources: the read-tool rows behind this turn's figures.
            // Attach to the current assistant message so the view can render
            // "based on these N transactions" under the answer. A turn with no
            // read tool never sends this frame, so the chip only shows when the
            // Clerk actually grounded its answer in data.
            const sources = data as AssistantSources;
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last?.role === "assistant") {
                next[next.length - 1] = { ...last, sources };
              }
              return next;
            });
          } else if (
            eventType === "crisis" ||
            eventType === "dispute" ||
            eventType === "tax_resource"
          ) {
            // Safety/compliance short-circuits: the body arrives as a `token`
            // frame too; just stop the spinner so the static resource shows.
            setIsLoading(false);
          } else if (eventType === "done") {
            setIsLoading(false);
          }
        };

        while (true) {
          if (controller.signal.aborted) break;  // F3 — bail on unmount/abort
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
        // F3 — an abort (unmount / cancellation) is normal, not an error: don't
        // log it or surface a toast, and skip the setState below if we're torn down.
        if (controller.signal.aborted || (error as Error)?.name === "AbortError") {
          return;
        }
        console.error("Error sending message:", error);
        setIsLoading(false);
      } finally {
        // Only clear loading/busy if this send still owns the active controller
        // (a later send replaced it, or unmount aborted us).
        if (abortRef.current === controller) abortRef.current = null;
        busyRef.current = false;
        setIsStreaming(false);
      }
    },
    [navigate]
  );

  const clear = useCallback(async () => {
    const clearUrl = `${apiBase}/assistant/clear/`;
    const doFetch = () => fetch(clearUrl, { method: "POST", credentials: "include" });
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
  }, [navigate]);

  const dismissProposal = useCallback(() => setProposal(null), []);
  const dismissBridge = useCallback(() => setBridge(null), []);

  return {
    messages,
    isLoading,
    isStreaming,
    actionMessages,
    proposal,
    bridge,
    send,
    clear,
    dismissProposal,
    dismissBridge,
  };
}
