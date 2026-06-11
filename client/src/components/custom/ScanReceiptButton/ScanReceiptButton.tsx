import { useRef, useState } from "react";
import { Loader2, ScanLine } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useStore } from "@/store/store";
import { useToast } from "@/hooks/useToast";
import { ReceiptDraft } from "@/types";
import { ALLOWED_RECEIPT_TYPES, validateReceiptFile } from "@/lib/receipt";

interface ScanReceiptButtonProps {
  /** Called with the extracted draft so the parent can open a prefilled form. */
  onScanned: (draft: ReceiptDraft) => void;
}

/**
 * Header quick-action: pick/snap a receipt and jump straight into a prefilled
 * transaction. It owns the file input and scan state only — the parent renders
 * the (shared) TransactionDialog and opens it with the returned draft.
 */
export function ScanReceiptButton({ onScanned }: ScanReceiptButtonProps) {
  const scanReceipt = useStore((s) => s.scanReceipt);
  const { toast } = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [scanning, setScanning] = useState(false);

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
    try {
      const draft = await scanReceipt(file);
      onScanned(draft);
    } catch (error) {
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ??
        "Could not read the receipt. Please enter the transaction manually.";
      toast({ variant: "destructive", title: "Scan failed", description: detail });
    } finally {
      setScanning(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <>
      <Button
        type="button"
        variant="outline"
        disabled={scanning}
        aria-busy={scanning}
        onClick={() => inputRef.current?.click()}
      >
        {scanning ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <ScanLine className="h-4 w-4" />
        )}
        {scanning ? "Scanning…" : "Scan Receipt"}
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept={ALLOWED_RECEIPT_TYPES.join(",")}
        capture="environment"
        className="hidden"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />
    </>
  );
}
