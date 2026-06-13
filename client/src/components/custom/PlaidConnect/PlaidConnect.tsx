import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { useNavigate } from "react-router-dom";
import { useToast } from "@/hooks/useToast";
import { useStore } from "@/store/store";
import { usePlaidReady, type PlaidHandler } from "@/lib/plaid";
import styles from "./PlaidConnect.module.css";

export function PlaidConnect() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const { linkToken, fetchLinkToken, exchangePublicToken } = useStore();
  const [plaidHandler, setPlaidHandler] = useState<PlaidHandler | null>(null);
  const plaidReady = usePlaidReady();
  // Keep the latest exchange handler in a ref so the create() effect doesn't
  // re-run (and re-create/leak handlers) on every render that changes a closure.
  const onSuccessRef = useRef<
    (publicToken: string, name: string) => Promise<void>
  >(async () => {});

  onSuccessRef.current = async (publicToken, name) => {
    try {
      await exchangePublicToken(publicToken, name);
      toast({
        title: "Account Connected",
        description: `Successfully connected ${name}`,
      });
      navigate("/?new-account=true");
    } catch {
      // An unhandled exchange failure would leave the user stuck with no signal;
      // surface it so they can retry.
      toast({
        variant: "destructive",
        title: "Could not connect your bank",
        description: "The connection couldn't be completed. Please try again.",
      });
    }
  };

  useEffect(() => {
    if (!linkToken) fetchLinkToken();
  }, [linkToken, fetchLinkToken]);

  useEffect(() => {
    if (!linkToken || !plaidReady || !window.Plaid) return;
    const handler = window.Plaid.create({
      token: linkToken,
      onSuccess: (publicToken, metadata) =>
        onSuccessRef.current(publicToken, metadata.institution.name),
      onExit: (err) => {
        if (err != null) console.error("Error during Link flow:", err);
      },
      onEvent: (eventName, metadata) => console.log("Event:", eventName, metadata),
    });
    setPlaidHandler(handler);
    // Tear the handler down on cleanup so re-creating it (new token, unmount)
    // doesn't leak the previous Plaid Link iframe/listeners.
    return () => {
      handler.destroy?.();
      setPlaidHandler(null);
    };
  }, [linkToken, plaidReady]);

  return (
    <div className={styles.container}>
      <div className={styles.content}>
        <h1 className={styles.title}>Connect Your Bank Account</h1>
        <p className={styles.description}>
          Securely connect your bank account to track your transactions and manage your budget.
        </p>
        <Button
          onClick={() => plaidHandler?.open()}
          className={styles.button}
          disabled={!plaidHandler}
        >
          {plaidHandler ? "Connect a Bank Account" : "Preparing secure link…"}
        </Button>
      </div>
    </div>
  );
}
