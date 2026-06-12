/**
 * <SagaChapter /> — the weekly chapter surface (v4 §8.1, task 5).
 *
 * Appears as a card on Overview on Sunday. The chapter body is prose (no digits
 * — the engine fills numbers via the surface), and it ALWAYS terminates in
 * exactly one tappable action rendered as the final block: one button. Dismiss
 * is free. Hidden in off mode (cost honesty — nothing is generated there).
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useFlags } from "@/store/gameMode";
import api from "@/lib/api";

interface Chapter {
  title: string;
  body: string;
  archetype_key: string;
  action: { kind: string; label: string; deep_link: string };
  fallback?: boolean;
}

export function SagaChapter() {
  const { gameLayer } = useFlags();
  const [chapter, setChapter] = useState<Chapter | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    if (!gameLayer) return;
    api
      .get("/game/chapter/")
      .then((r) => setChapter(r.data.chapter))
      .catch(() => {});
  }, [gameLayer]);

  if (!gameLayer || !chapter || dismissed) return null;

  return (
    <Card data-testid="saga-chapter">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="font-display text-lg">{chapter.title}</CardTitle>
        <button
          data-testid="chapter-dismiss"
          onClick={() => setDismissed(true)}
          className="text-xs uppercase tracking-wide text-muted-foreground hover:text-foreground"
        >
          Dismiss
        </button>
      </CardHeader>
      <CardContent>
        <p data-testid="chapter-body" className="whitespace-pre-line text-sm leading-relaxed text-muted-foreground">
          {chapter.body}
        </p>

        {/* The ONE action — the chapter's final block, a single button. */}
        <div className="mt-4">
          <button
            data-testid="chapter-action"
            onClick={() => navigate(chapter.action.deep_link)}
            className="press border border-gold/60 bg-gold/10 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-gold shadow-plate"
          >
            {chapter.action.label}
          </button>
        </div>
      </CardContent>
    </Card>
  );
}

export default SagaChapter;
