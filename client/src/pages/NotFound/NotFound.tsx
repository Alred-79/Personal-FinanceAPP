import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="mx-auto flex min-h-[60vh] max-w-xl flex-col items-center justify-center text-center">
      <p className="dept-label">Folio not found · 404</p>
      <h1 className="mt-3 font-display text-4xl font-semibold">This page is not in the ledger</h1>
      <p className="mt-3 font-sans text-sm leading-6 text-muted-foreground">
        The address may be old or mistyped. Your financial records have not been changed.
      </p>
      <Button className="mt-6 min-h-11" asChild>
        <Link to="/">Return to Overview</Link>
      </Button>
    </div>
  );
}
