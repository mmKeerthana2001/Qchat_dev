import { useEffect } from "react";
import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, useNavigate, useLocation } from "react-router-dom";
import { ThemeProvider } from "@/components/ThemeProvider";
import { ChatLayout } from "./components/layout/ChatLayout";
import Login from "./pages/Login";
import NotFound from "./pages/NotFound";
import CandidateChat from "./components/layout/CandidateChat";

// 👇 Import your new VoiceInteraction page/component
import VoiceInteraction from "./pages/VoiceInteraction"; // <-- make sure this file exists

const queryClient = new QueryClient();

const ProtectedRoute = ({ children }: { children: JSX.Element }) => {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const sessionId = localStorage.getItem("session_id");
    const params = new URLSearchParams(location.search);
    const sessionIdFromUrl = params.get("session_id");

    console.log("ProtectedRoute - Checking authentication:", { sessionId, sessionIdFromUrl });

    if (sessionIdFromUrl) {
      console.log("ProtectedRoute - Found session_id in URL, storing:", sessionIdFromUrl);
      localStorage.setItem("session_id", sessionIdFromUrl);
      navigate("/chat", { replace: true });
    } else if (!sessionId) {
      console.log("ProtectedRoute - No session_id found, redirecting to /");
      navigate("/");
    }
  }, [navigate, location.search]);

  return children;
};

const App = () => (
  <QueryClientProvider client={queryClient}>
    <ThemeProvider defaultTheme="dark">
      <TooltipProvider>
        <Toaster />
        <Sonner />
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Login />} />
            <Route
              path="/chat"
              element={
                <ProtectedRoute>
                  <ChatLayout />
                </ProtectedRoute>
              }
            />
            <Route path="/candidate-chat" element={<CandidateChat />} />

            {/* ✅ New voice interaction route */}
            <Route
              path="/voice-interaction"
              element={
                <ProtectedRoute>
                  <VoiceInteraction />
                </ProtectedRoute>
              }
            />

            {/* Catch-all for invalid routes */}
            <Route path="*" element={<NotFound />} />
          </Routes>
        </BrowserRouter>
      </TooltipProvider>
    </ThemeProvider>
  </QueryClientProvider>
);

export default App;
