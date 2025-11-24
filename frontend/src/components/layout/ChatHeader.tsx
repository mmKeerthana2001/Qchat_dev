import { Button } from "@/components/ui/button";
import { Sun, Moon } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useTheme } from "@/components/ThemeProvider";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";

interface ChatHeaderProps {}

export function ChatHeader({}: ChatHeaderProps) {
  const { setTheme, theme } = useTheme();

  return (
    <header className="border-b border-border bg-card/80 backdrop-blur-xl p-3 shadow-sm">
      <div className="max-w-7xl mx-auto flex items-center justify-end">
        {/* Right Section: Theme Toggle and Avatar */}
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="h-8 w-8 rounded-full hover:bg-primary/10 transition-colors duration-200"
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          >
            {theme === "dark" ? (
              <Sun className="h-4 w-4 text-foreground/80" />
            ) : (
              <Moon className="h-4 w-4 text-foreground/80" />
            )}
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Avatar className="h-8 w-8 cursor-pointer ring-1 ring-primary/20 hover:ring-primary/40 transition-all duration-200">
                <AvatarFallback className="bg-gradient-primary text-primary-foreground text-sm">
                  U
                </AvatarFallback>
              </Avatar>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-40 rounded-lg border border-border bg-card/95 p-1 shadow-lg">
              <DropdownMenuItem className="text-sm rounded-md hover:bg-primary/10 cursor-pointer">
                Profile
              </DropdownMenuItem>
              <DropdownMenuItem className="text-sm rounded-md hover:bg-primary/10 cursor-pointer">
                Settings
              </DropdownMenuItem>
              <DropdownMenuItem className="text-sm rounded-md hover:bg-destructive/10 text-destructive cursor-pointer">
                Sign Out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  );
}