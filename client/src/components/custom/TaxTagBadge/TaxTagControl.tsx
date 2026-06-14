import { useEffect, useState } from "react";
import { Tag, Loader2 } from "lucide-react";
import api from "@/lib/api";
import { TaxBucket, TaxTag } from "@/types";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/useToast";
import { TaxTagBadge } from "./TaxTagBadge";

// The bucket registry is static + tiny — fetch once and share across every row.
let _bucketsCache: TaxBucket[] | null = null;
async function loadBuckets(): Promise<TaxBucket[]> {
  if (_bucketsCache) return _bucketsCache;
  const { data } = await api.get("/tax/buckets/");
  _bucketsCache = data;
  return data;
}

/**
 * A per-transaction tax-bucket control: shows the current tag as a chip and,
 * behind a popover, lets the user pick a Schedule-C bucket + business/personal.
 * Organization only — it records the user's tag; it never asserts deductibility.
 *
 * Lazy by design: the current tag is only fetched when the popover opens, so a
 * long ledger doesn't fan out N tag requests on render. Rendered only when the
 * tax feature is enabled (the caller gates on the store flag).
 */
export function TaxTagControl({
  txType,
  txId,
  onChange,
}: {
  txType: "expense" | "income";
  txId: number;
  onChange?: () => void;
}) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [buckets, setBuckets] = useState<TaxBucket[]>([]);
  const [tag, setTag] = useState<TaxTag | null>(null);
  const [bucket, setBucket] = useState<string>("");
  const [biz, setBiz] = useState<"business" | "personal">("business");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loadedOnce, setLoadedOnce] = useState(false);

  // Expense buckets for an expense, income buckets for income (orthogonal axis).
  const choices = buckets.filter((b) => b.kind === txType);

  useEffect(() => {
    if (!open || loadedOnce) return;
    setLoading(true);
    Promise.all([
      loadBuckets(),
      api
        .get(`/tax/tags/${txType}/${txId}/`)
        .then((r) => r.data as TaxTag)
        .catch(() => null),
    ])
      .then(([bs, existing]) => {
        setBuckets(bs);
        if (existing) {
          setTag(existing);
          setBucket(existing.bucket);
          setBiz(existing.business_personal);
        }
      })
      .finally(() => {
        setLoading(false);
        setLoadedOnce(true);
      });
  }, [open, loadedOnce, txType, txId]);

  async function save() {
    if (!bucket) {
      toast({ title: "Pick a bucket", variant: "destructive" });
      return;
    }
    setSaving(true);
    try {
      const { data } = await api.put(`/tax/tags/${txType}/${txId}/`, {
        bucket,
        business_personal: biz,
      });
      setTag(data);
      setOpen(false);
      onChange?.();
    } catch {
      toast({ title: "Could not tag", variant: "destructive" });
    } finally {
      setSaving(false);
    }
  }

  async function clear() {
    setSaving(true);
    try {
      await api.delete(`/tax/tags/${txType}/${txId}/`);
      setTag(null);
      setBucket("");
      setOpen(false);
      onChange?.();
    } catch {
      toast({ title: "Could not remove tag", variant: "destructive" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          className="inline-flex items-center gap-1 text-muted-foreground transition-colors hover:text-gold"
          aria-label="Tax tag"
          onClick={(e) => e.stopPropagation()}
        >
          {tag ? (
            <TaxTagBadge
              label={tag.bucket_label}
              businessPersonal={tag.business_personal}
              deductibleBps={tag.deductible_bps}
            />
          ) : (
            <Tag className="h-[14px] w-[14px]" />
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-72 space-y-3"
        onClick={(e) => e.stopPropagation()}
      >
        <p className="dept-label">Tax bucket · organization only</p>
        {loading ? (
          <div className="flex justify-center py-4">
            <Loader2 className="h-4 w-4 animate-spin text-gold" />
          </div>
        ) : (
          <>
            <Select value={bucket} onValueChange={setBucket}>
              <SelectTrigger>
                <SelectValue placeholder="Pick a Schedule-C bucket" />
              </SelectTrigger>
              <SelectContent>
                {choices.map((b) => (
                  <SelectItem key={b.key} value={b.key}>
                    {b.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <div className="flex gap-2">
              {(["business", "personal"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setBiz(v)}
                  className={`flex-1 border px-2 py-1 font-mono text-[10px] uppercase tracking-[0.1em] transition-colors ${
                    biz === v
                      ? "border-rule-strong/60 bg-secondary text-secondary-foreground"
                      : "border-rule-strong/30 text-muted-foreground"
                  }`}
                >
                  {v}
                </button>
              ))}
            </div>

            <div className="flex justify-between gap-2 pt-1">
              {tag && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={clear}
                  disabled={saving}
                  className="text-debit"
                >
                  Remove
                </Button>
              )}
              <Button
                size="sm"
                onClick={save}
                disabled={saving}
                className="press ml-auto"
              >
                {saving ? "Saving…" : "Save tag"}
              </Button>
            </div>
            <p className="text-[10px] text-muted-foreground">
              Records your tag — it does not assert this is deductible.
            </p>
          </>
        )}
      </PopoverContent>
    </Popover>
  );
}

export default TaxTagControl;
