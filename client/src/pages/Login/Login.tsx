import { useState } from "react";
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
import { useNavigate } from "react-router-dom";
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
      {/* Engraved backdrop */}
      <div className="pointer-events-none absolute -left-32 -top-32 text-gold/10">
        <Guilloche size={520} rings={9} seed={21} animate />
      </div>
      <div className="pointer-events-none absolute -bottom-40 -right-40 text-gold/10">
        <Guilloche size={620} rings={10} seed={88} animate />
      </div>

      <div className="relative flex flex-col items-center gap-3 text-center animate-ink-in">
        <span className="text-gold">
          <Brandmark size={56} />
        </span>
        <div>
          <p className="dept-label">Department of Personal Accounts</p>
          <h1 className="font-display text-4xl font-semibold tracking-tight">
            The Ledger
          </h1>
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
    </div>
  );
}
