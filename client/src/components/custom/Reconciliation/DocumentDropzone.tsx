import { useRef, useState, DragEvent } from "react";
import { Loader2, FileUp } from "lucide-react";
import { useStore } from "@/store/store";
import { useToast } from "@/hooks/useToast";
import { ImportSession } from "@/types";
import { ALLOWED_IMPORT_TYPES, validateImportFile } from "@/lib/imports";

interface DocumentDropzoneProps {
  /** Which account the imported transactions belong to. */
  accountId: number;
  /** Called with the review payload once extraction + reconcile succeeds. */
  onExtracted: (session: ImportSession) => void;
  /** Notifies the parent when extraction starts/stops. */
  onExtracting?: (extracting: boolean) => void;
}

/**
 * Click-or-drag uploader for a messy statement (image or PDF). Validates the
 * file client-side, posts it to the Import Anything endpoint via
 * `importDocument`, and hands the resulting review payload back. Mirrors
 * `ReceiptDropzone` but accepts PDFs and yields a full reconcile session.
 */
export function DocumentDropzone({
  accountId,
  onExtracted,
  onExtracting,
}: DocumentDropzoneProps) {
  const importDocument = useStore((s) => s.importDocument);
  const { toast } = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [dragActive, setDragActive] = useState(false);

  const handleFile = async (file: File | undefined) => {
    if (!file) return;
    if (!accountId) {
      toast({
        variant: "destructive",
        title: "Pick an account first",
        description: "Choose which account this statement belongs to.",
      });
      return;
    }

    const validationError = validateImportFile(file);
    if (validationError) {
      toast({
        variant: "destructive",
        title: "Can't read that file",
        description: validationError,
      });
      return;
    }

    setBusy(true);
    onExtracting?.(true);
    try {
      const session = await importDocument(file, accountId);
      onExtracted(session);
    } catch (error) {
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ??
        "Could not read the statement. Try a clearer file or paste the text.";
      toast({ variant: "destructive", title: "Import failed", description: detail });
    } finally {
      setBusy(false);
      onExtracting?.(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const onDrop = (e: DragEvent<HTMLButtonElement>) => {
    e.preventDefault();
    setDragActive(false);
    if (busy) return;
    handleFile(e.dataTransfer.files?.[0]);
  };

  return (
    <button
      type="button"
      onClick={() => !busy && inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setDragActive(true);
      }}
      onDragLeave={() => setDragActive(false)}
      onDrop={onDrop}
      disabled={busy}
      aria-busy={busy}
      className={`flex w-full flex-col items-center justify-center gap-2 rounded-none border border-dashed px-4 py-8 font-sans text-sm font-medium transition-colors ${
        dragActive
          ? "border-gold bg-gold/10 text-gold"
          : "border-rule-strong/50 text-muted-foreground hover:bg-wash hover:text-foreground"
      } shadow-plate disabled:cursor-not-allowed disabled:opacity-70`}
    >
      {busy ? (
        <>
          <Loader2 className="h-5 w-5 animate-spin" />
          Reading the statement…
        </>
      ) : (
        <>
          <FileUp className="h-5 w-5" />
          <span>Drop a statement, screenshot, or PDF — or click to choose</span>
          <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/70">
            PNG · JPEG · WebP · PDF — up to 15 MB
          </span>
        </>
      )}
      <input
        ref={inputRef}
        type="file"
        accept={ALLOWED_IMPORT_TYPES.join(",")}
        className="hidden"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />
    </button>
  );
}
