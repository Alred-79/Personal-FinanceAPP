import { useRef, useState, DragEvent } from "react";
import { Loader2, ScanLine } from "lucide-react";
import { useStore } from "@/store/store";
import { useToast } from "@/hooks/useToast";
import { ReceiptDraft } from "@/types";
import { ALLOWED_RECEIPT_TYPES, validateReceiptFile } from "@/lib/receipt";

interface ReceiptDropzoneProps {
  /** Called with the extracted draft once a receipt is scanned successfully. */
  onScanned: (draft: ReceiptDraft) => void;
  /** Notifies the parent when a scan starts/stops (e.g. to disable submit). */
  onScanning?: (scanning: boolean) => void;
}

/**
 * Click-or-drag receipt uploader. Validates the file client-side, posts it to
 * the vision endpoint via `scanReceipt`, and hands the resulting draft back to
 * the parent. Surfaces errors as toasts; the form stays manually editable.
 */
export function ReceiptDropzone({ onScanned, onScanning }: ReceiptDropzoneProps) {
  const scanReceipt = useStore((s) => s.scanReceipt);
  const { toast } = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [scanning, setScanning] = useState(false);
  const [dragActive, setDragActive] = useState(false);

  const handleFile = async (file: File | undefined) => {
    if (!file) return;

    const validationError = validateReceiptFile(file);
    if (validationError) {
      toast({
        variant: "destructive",
        title: "Can't scan that file",
        description: validationError,
      });
      return;
    }

    setScanning(true);
    onScanning?.(true);
    try {
      const draft = await scanReceipt(file);
      onScanned(draft);
      toast({
        title: "Receipt scanned",
        description: "Review the details below, then add the transaction.",
      });
    } catch (error) {
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ??
        "Could not read the receipt. Please enter the transaction manually.";
      toast({
        variant: "destructive",
        title: "Scan failed",
        description: detail,
      });
    } finally {
      setScanning(false);
      onScanning?.(false);
      // Allow re-selecting the same file (onChange won't fire otherwise).
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const onDrop = (e: DragEvent<HTMLButtonElement>) => {
    e.preventDefault();
    setDragActive(false);
    if (scanning) return;
    handleFile(e.dataTransfer.files?.[0]);
  };

  return (
    <button
      type="button"
      onClick={() => !scanning && inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setDragActive(true);
      }}
      onDragLeave={() => setDragActive(false)}
      onDrop={onDrop}
      disabled={scanning}
      aria-busy={scanning}
      className={`flex w-full items-center justify-center gap-2 rounded-none border border-dashed px-4 py-3 font-sans text-sm font-medium transition-colors ${
        dragActive
          ? "border-gold bg-gold/10 text-gold"
          : "border-rule-strong/50 text-muted-foreground hover:bg-wash hover:text-foreground"
      } shadow-plate disabled:cursor-not-allowed disabled:opacity-70`}
    >
      {scanning ? (
        <>
          <Loader2 className="h-4 w-4 animate-spin" />
          Reading receipt…
        </>
      ) : (
        <>
          <ScanLine className="h-4 w-4" />
          Scan a receipt to auto-fill
        </>
      )}
      {/* No `capture` attr: forcing capture="environment" blocked picking an
          existing receipt photo from the gallery on mobile. Omitting it lets the
          OS offer BOTH the camera and the gallery; `accept` still scopes to
          allowed image types. */}
      <input
        ref={inputRef}
        type="file"
        accept={ALLOWED_RECEIPT_TYPES.join(",")}
        className="hidden"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />
    </button>
  );
}
