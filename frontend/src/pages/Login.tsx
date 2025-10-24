import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/use-toast";

const Login = () => {
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { toast } = useToast();

  useEffect(() => {
    // Handle token from callback
    const token = searchParams.get("token");
    if (token) {
      localStorage.setItem("auth_token", token);
      navigate("/chat");
    }
  }, [searchParams, navigate]);

  const handleMicrosoftLogin = async () => {
    setIsLoading(true);
    try {
      // Redirect to backend login endpoint
      window.location.href = "http://localhost:8000/login";
    } catch (error) {
      setIsLoading(false);
      toast({
        title: "Login Error",
        description: "Failed to initiate Microsoft login. Please try again.",
        variant: "destructive",
        duration: 10000,
      });
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-background to-muted/20 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo and Title */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-primary/10 rounded-xl mb-4">
            <span className="text-2xl font-bold text-primary">Q</span>
          </div>
          <h1 className="text-3xl font-bold text-foreground mb-2">QChat</h1>
          <p className="text-muted-foreground">Professional AI Assistant</p>
        </div>

        {/* Login Card */}
        <div className="bg-card/80 backdrop-blur-sm border border-border rounded-lg p-8 shadow-lg">
          <div className="text-center mb-6">
            <h2 className="text-xl font-semibold text-foreground mb-2">
              Welcome Back
            </h2>
            <p className="text-sm text-muted-foreground">
              Sign in to continue to your professional AI assistant
            </p>
          </div>

          {/* Microsoft Login Button */}
          <Button
            onClick={handleMicrosoftLogin}
            disabled={isLoading}
            className="w-full h-12 bg-white hover:bg-gray-50 text-gray-900 border border-gray-200 font-medium transition-all duration-200 shadow-sm hover:shadow-md disabled:opacity-50"
            variant="outline"
          >
            {isLoading ? (
              <div className="flex items-center gap-3">
                <div className="w-4 h-4 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
                <span>Signing in...</span>
              </div>
            ) : (
              <div className="flex items-center gap-3">
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <path
                    d="M11.4 24H0V12.6h11.4V24zM24 24H12.6V12.6H24V24zM11.4 11.4H0V0h11.4v11.4zM24 11.4H12.6V0H24v11.4z"
                    fill="#00BCF2"
                  />
                  <path
                    d="M11.4 11.4H0V0h11.4v11.4z"
                    fill="#00BCF2"
                  />
                  <path
                    d="M24 11.4H12.6V0H24v11.4z"
                    fill="#00BCF2"
                  />
                  <path
                    d="M11.4 24H0V12.6h11.4V24z"
                    fill="#00BCF2"
                  />
                  <path
                    d="M24 24H12.6V12.6H24V24z"
                    fill="#FFB900"
                  />
                </svg>
                <span>Continue with Microsoft</span>
              </div>
            )}
          </Button>

          <div className="mt-6 text-center">
            <p className="text-xs text-muted-foreground">
              Secure enterprise-grade authentication powered by Microsoft
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="text-center mt-8">
          <p className="text-xs text-muted-foreground">
            © 2024 QChat. Enterprise AI Solutions.
          </p>
        </div>
      </div>
    </div>
  );
};

export default Login;