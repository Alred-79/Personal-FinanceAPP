import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { useNavigate } from "react-router-dom";
import { useToast } from "@/hooks/useToast";
import { useStore } from "@/store/store";
import styles from "./PlaidConnect.module.css";

declare global {
  interface Window {
    Plaid: {
      create: (config: {
        token: string;
        onSuccess: (publicToken: string, metadata: { institution: { name: string } }) => void;
        onExit: (err: Error | null) => void;
        onEvent: (eventName: string, metadata: unknown) => void;
      }) => { open: () => void };
    };
  }
}

export function PlaidConnect() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const { linkToken, fetchLinkToken, exchangePublicToken } = useStore();
  const [plaidHandler, setPlaidHandler] = useState<{ open: () => void } | null>(null);

  useEffect(() => {
    if (!linkToken) fetchLinkToken();
  }, [linkToken, fetchLinkToken]);

  useEffect(() => {
    if (!linkToken || !window.Plaid) return;
    const handler = window.Plaid.create({
      token: linkToken,
      onSuccess: async (publicToken, metadata) => {
        await exchangePublicToken(publicToken, metadata.institution.name);
        toast({
          title: "Account Connected",
          description: `Successfully connected ${metadata.institution.name}`,
        });
        navigate("/?new-account=true");
      },
      onExit: (err) => {
        if (err != null) console.error("Error during Link flow:", err);
      },
      onEvent: (eventName, metadata) => console.log("Event:", eventName, metadata),
    });
    setPlaidHandler(handler);
  }, [linkToken, navigate, toast, exchangePublicToken]);

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
          Connect a Bank Account
        </Button>
      </div>
    </div>
  );
}
