import { useCallback, useEffect, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useToast } from "@/hooks/useToast";
import { useStore } from "@/store/store";
import api from "@/lib/api";
import { AxiosError } from "axios";
import { Brandmark } from "@/components/layout/Brandmark";
import { Guilloche, GuillocheBand } from "@/components/engraving/Guilloche";
import { loadCapabilities } from "@/lib/capabilities";

/**
 * Where to land after signing in. `?next=` lets a public page (the landing's
 * "Connect your AI") point through login at a specific folio. Only same-origin
 * absolute paths are honoured — a leading "//" or any scheme would be an open
 * redirect, so anything else falls back to the dashboard.
 */
function safeNext(raw: string | null): string {
  if (!raw) return "/";
  if (!raw.startsWith("/") || raw.startsWith("//")) return "/";
  return raw;
}

export default function Login() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const next = safeNext(searchParams.get("next"));
  const { toast } = useToast();
  const [isLoading, setIsLoading] = useState(false);
  const [demoAvailability, setDemoAvailability] = useState<
    "checking" | "hidden" | "ready" | "unavailable"
  >("checking");
  const [demoError, setDemoError] = useState<string | null>(null);
  const [registrationOpen, setRegistrationOpen] = useState<boolean | null>(null);

  const checkDemoStatus = useCallback(async (active: () => boolean = () => true) => {
    setDemoError(null);
    setDemoAvailability("checking");
    try {
      const response = await api.get("/demo-status");
      if (!active()) return;
      if (!response.data?.enabled) {
        setDemoAvailability("hidden");
      } else {
        // Fail closed unless the backend has verified the current schema and
        // canonical dataset. An older `enabled`-only response must not expose a
        // button that can navigate into a partial, error-filled showcase.
        setDemoAvailability(response.data?.ready === true ? "ready" : "unavailable");
      }
    } catch {
      // Without a confirmed enabled flag, fail closed just as a normal
      // non-demo deployment does.
      if (active()) setDemoAvailability("hidden");
    }
  }, []);

  // Ask whether the showcase is both enabled and provisioned. An enabled but
  // unready deployment gets a quiet retry state instead of a button that is
  // guaranteed to fail after the visitor clicks it.
  useEffect(() => {
    let active = true;
    void checkDemoStatus(() => active);
    void loadCapabilities()
      .then((capabilities) => {
        if (active) setRegistrationOpen(capabilities.registration_open === true);
      })
      .catch(() => {
        if (active) setRegistrationOpen(false);
      });
    return () => {
      active = false;
    };
  }, [checkDemoStatus]);

  const handleDemo = async () => {
    setIsLoading(true);
    setDemoError(null);
    try {
      await useStore.getState().bootstrapDemoSession();
      toast({
        title: "Demo data opened",
        description: "You're exploring a pre-filled financial story. Nothing here is connected to a real bank.",
      });
      navigate(next);
    } catch {
      // Keep this local and singular. Page-level fetchers never mount because
      // the bootstrap is atomic, so one unavailable message replaces the old
      // cascade of destructive "cannot load" toasts.
      setDemoError("The demo is being refreshed. Please try again in a moment.");
    } finally {
      setIsLoading(false);
    }
  };

  const [loginData, setLoginData] = useState({
    username: "",
    password: "",
  });

  const [signupData, setSignupData] = useState({
    fullName: "",
    username: "",
    email: "",
    password: "",
    confirmPassword: "",
  });

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      const formData = new FormData();
      formData.append("username", loginData.username);
      formData.append("password", loginData.password);

      // Use axios directly for token endpoint since it's not part of the API routes
      await api.post("/token", formData, {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      });

      toast({
        title: "Login successful",
        description: "Welcome back!",
      });

      // Set isLoggedIn to true
      useStore.getState().beginAuthenticatedSession();

      // Redirect to dashboard or home
      navigate(next);
    } catch (error) {
      const axiosError = error as AxiosError<{ detail: string }>;
      toast({
        variant: "destructive",
        title: "Login failed",
        description:
          axiosError.response?.data?.detail || "An error occurred during login",
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();

    if (signupData.password !== signupData.confirmPassword) {
      toast({
        variant: "destructive",
        title: "Passwords don't match",
        description: "Please make sure your passwords match",
      });
      return;
    }

    setIsLoading(true);

    try {
      await api.post("/signup", {
        full_name: signupData.fullName,
        username: signupData.username,
        email: signupData.email,
        password: signupData.password,
      });

      toast({
        title: "Account opened",
        description: "Welcome to The Ledger.",
      });

      // Set isLoggedIn to true
      useStore.getState().beginAuthenticatedSession();

      // Redirect to dashboard or home
      navigate(next);
    } catch (error) {
      const axiosError = error as AxiosError<{ detail: string | { msg: string }[] }>;
      const detail = axiosError.response?.data?.detail;
      const description =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
          ? detail.map((d) => d.msg).join(" ")
          : "An error occurred during signup";
      toast({
        variant: "destructive",
        title: "Signup failed",
        description,
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="relative flex min-h-screen w-full flex-col items-center justify-center gap-6 overflow-hidden bg-background p-4">
      {/* Engraved backdrop — corner rosettes + a breathing centre guilloché,
          matching the landing's living plate. */}
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-rule-strong/[0.06] dark:text-rule-strong/[0.1]"
      >
        <Guilloche size={760} rings={9} seed={42} animate />
      </div>
      <div aria-hidden className="pointer-events-none absolute -left-32 -top-32 text-gold/10">
        <Guilloche size={520} rings={9} seed={21} animate />
      </div>
      <div aria-hidden className="pointer-events-none absolute -bottom-40 -right-40 text-gold/10">
        <Guilloche size={620} rings={10} seed={88} animate />
      </div>

      {/* Back to the public landing */}
      <Link
        to="/welcome"
        className="absolute left-4 top-4 z-10 flex items-center gap-1.5 font-sans text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground transition-colors hover:text-foreground"
      >
        <span aria-hidden>←</span> The Ledger
      </Link>

      <div className="relative flex flex-col items-center gap-3 text-center animate-ink-in">
        <span className="text-gold">
          <Brandmark size={56} />
        </span>
        <div>
          <p className="dept-label">Department of Personal Accounts</p>
          <h1 className="font-display text-4xl font-semibold tracking-tight">
            The Ledger
          </h1>
          <p className="mt-1 font-sans text-sm text-muted-foreground">
            Know what&rsquo;s safe. See what comes next.
          </p>
        </div>
      </div>

      <Card className="relative w-full max-w-md animate-rise-in delay-2">
        <div className="text-gold/40">
          <GuillocheBand height={14} waves={4} seed={5} />
        </div>
        <CardHeader>
          <CardTitle className="font-display text-xl normal-case tracking-normal text-foreground">
            Present your credentials
          </CardTitle>
          <CardDescription>
            {registrationOpen === null
              ? "Checking whether this instance accepts new accounts…"
              : registrationOpen
              ? "Sign in to your ledger, or open one to see your full financial picture."
              : "Registration is closed on this instance. Sign in with the owner account."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="login" className="w-full">
            <TabsList className={`grid w-full ${registrationOpen === true ? "grid-cols-2" : "grid-cols-1"}`}>
              <TabsTrigger value="login">Login</TabsTrigger>
              {registrationOpen === true && <TabsTrigger value="signup">Sign Up</TabsTrigger>}
            </TabsList>

            <TabsContent value="login">
              <form onSubmit={handleLogin} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="login-username">Username</Label>
                  <Input
                    id="login-username"
                    type="text"
                    placeholder="Enter your username"
                    value={loginData.username}
                    onChange={(e) =>
                      setLoginData({ ...loginData, username: e.target.value })
                    }
                    disabled={isLoading}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="login-password">Password</Label>
                  <Input
                    id="login-password"
                    type="password"
                    placeholder="Enter your password"
                    value={loginData.password}
                    onChange={(e) =>
                      setLoginData({ ...loginData, password: e.target.value })
                    }
                    disabled={isLoading}
                  />
                </div>
                <Button type="submit" className="w-full" disabled={isLoading}>
                  {isLoading ? "Logging in..." : "Login"}
                </Button>
              </form>

              {demoAvailability !== "hidden" && demoAvailability !== "checking" && (
                <div className="mt-5 space-y-3">
                  <div className="flex items-center gap-3">
                    <span className="h-px flex-1 bg-rule/60" aria-hidden />
                    <span className="font-sans text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                      explore first
                    </span>
                    <span className="h-px flex-1 bg-rule/60" aria-hidden />
                  </div>
                  {demoAvailability === "ready" ? (
                    <>
                      <Button
                        type="button"
                        variant="outline"
                        className="w-full border-gold/40 text-foreground hover:bg-gold/10"
                        onClick={handleDemo}
                        disabled={isLoading}
                      >
                        {isLoading ? "Opening demo data…" : "View demo data"}
                      </Button>
                      <p className="text-center font-sans text-[11px] leading-relaxed text-muted-foreground">
                        No sign-up or bank connection. Explore pre-filled accounts,
                        budgets, goals, forecasts, subscriptions, debts, and scenarios.
                      </p>
                    </>
                  ) : (
                    <div className="text-center font-sans text-[11px] leading-relaxed text-muted-foreground">
                      <p>The demo data is being prepared.</p>
                      <button
                        type="button"
                        className="mt-1 min-h-11 px-3 font-semibold text-foreground underline decoration-rule-strong underline-offset-4 hover:text-gold"
                        onClick={() => void checkDemoStatus()}
                      >
                        Check again
                      </button>
                    </div>
                  )}
                  {demoError && (
                    <p
                      role="status"
                      className="text-center font-sans text-[11px] leading-relaxed text-muted-foreground"
                    >
                      {demoError}
                    </p>
                  )}
                </div>
              )}
            </TabsContent>

            {registrationOpen === true && <TabsContent value="signup">
              <form onSubmit={handleSignup} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="signup-fullname">Full Name</Label>
                  <Input
                    id="signup-fullname"
                    type="text"
                    placeholder="Enter your full name"
                    value={signupData.fullName}
                    onChange={(e) =>
                      setSignupData({ ...signupData, fullName: e.target.value })
                    }
                    disabled={isLoading}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="signup-username">Username</Label>
                  <Input
                    id="signup-username"
                    type="text"
                    placeholder="Choose a username"
                    value={signupData.username}
                    onChange={(e) =>
                      setSignupData({ ...signupData, username: e.target.value })
                    }
                    disabled={isLoading}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="signup-email">Email</Label>
                  <Input
                    id="signup-email"
                    type="email"
                    placeholder="Enter your email"
                    value={signupData.email}
                    onChange={(e) =>
                      setSignupData({ ...signupData, email: e.target.value })
                    }
                    disabled={isLoading}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="signup-password">Password</Label>
                  <Input
                    id="signup-password"
                    type="password"
                    placeholder="Choose a password"
                    value={signupData.password}
                    onChange={(e) =>
                      setSignupData({ ...signupData, password: e.target.value })
                    }
                    disabled={isLoading}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="signup-confirm-password">
                    Confirm Password
                  </Label>
                  <Input
                    id="signup-confirm-password"
                    type="password"
                    placeholder="Confirm your password"
                    value={signupData.confirmPassword}
                    onChange={(e) =>
                      setSignupData({
                        ...signupData,
                        confirmPassword: e.target.value,
                      })
                    }
                    disabled={isLoading}
                  />
                </div>
                <Button type="submit" className="w-full" disabled={isLoading}>
                  {isLoading ? "Creating account..." : "Sign Up"}
                </Button>
              </form>
            </TabsContent>}
          </Tabs>
        </CardContent>
      </Card>

      {/* Assurances — echoing the landing's promises. */}
      <div className="relative flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-[0.72rem] tracking-[0.04em] text-muted-foreground animate-rise-in delay-3">
        {["No card required", "Your data stays yours", "Read-only by default"].map(
          (t) => (
            <span key={t} className="flex items-center gap-1.5">
              <svg
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.4"
                className="text-gold"
                aria-hidden
              >
                <path d="M20 6 9 17l-5-5" />
              </svg>
              {t}
            </span>
          )
        )}
      </div>
    </div>
  );
}
