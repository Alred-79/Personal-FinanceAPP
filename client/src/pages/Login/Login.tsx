import { useEffect, useState } from "react";
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
import { Link, useNavigate } from "react-router-dom";
import { useToast } from "@/hooks/useToast";
import { useStore } from "@/store/store";
import api from "@/lib/api";
import { AxiosError } from "axios";
import { Brandmark } from "@/components/layout/Brandmark";
import { Guilloche, GuillocheBand } from "@/components/engraving/Guilloche";

export default function Login() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [isLoading, setIsLoading] = useState(false);
  const [demoEnabled, setDemoEnabled] = useState(false);

  // Ask the backend whether demo mode is on. The button only appears when the
  // gated /demo-login/ route actually exists (false in any normal deployment).
  useEffect(() => {
    let active = true;
    api
      .get("/demo-status")
      .then((res) => {
        if (active) setDemoEnabled(Boolean(res.data?.enabled));
      })
      .catch(() => {
        /* no demo button if the probe fails — fail closed */
      });
    return () => {
      active = false;
    };
  }, []);

  const handleDemo = async () => {
    setIsLoading(true);
    try {
      await api.post("/demo-login");
      toast({
        title: "Welcome to the demo",
        description: "You're exploring a pre-filled showcase account.",
      });
      useStore.setState({ isLoggedIn: true });
      navigate("/");
    } catch (error) {
      const axiosError = error as AxiosError<{ detail: string }>;
      toast({
        variant: "destructive",
        title: "Couldn't enter the demo",
        description:
          axiosError.response?.data?.detail ||
          "The demo is unavailable right now.",
      });
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
      useStore.setState({ isLoggedIn: true });

      // Redirect to dashboard or home
      navigate("/");
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
      useStore.setState({ isLoggedIn: true });

      // Redirect to dashboard or home
      navigate("/");
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
            Keep your money in good standing.
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
            Sign the register to enter, or open a new account.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="login" className="w-full">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="login">Login</TabsTrigger>
              <TabsTrigger value="signup">Sign Up</TabsTrigger>
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

              {demoEnabled && (
                <div className="mt-5 space-y-3">
                  <div className="flex items-center gap-3">
                    <span className="h-px flex-1 bg-rule/60" aria-hidden />
                    <span className="font-sans text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                      or
                    </span>
                    <span className="h-px flex-1 bg-rule/60" aria-hidden />
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full border-gold/40 text-foreground hover:bg-gold/10"
                    onClick={handleDemo}
                    disabled={isLoading}
                  >
                    {isLoading ? "Entering…" : "Enter the demo"}
                  </Button>
                  <p className="text-center font-sans text-[11px] text-muted-foreground">
                    No sign-up needed. Or type{" "}
                    <code className="rounded bg-muted px-1 py-0.5 font-mono text-[10px] text-foreground">
                      demo
                    </code>{" "}
                    /{" "}
                    <code className="rounded bg-muted px-1 py-0.5 font-mono text-[10px] text-foreground">
                      Demo123!
                    </code>{" "}
                    above.
                  </p>
                </div>
              )}
            </TabsContent>

            <TabsContent value="signup">
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
            </TabsContent>
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
