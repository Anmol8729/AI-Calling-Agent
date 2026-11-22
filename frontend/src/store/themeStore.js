import { create } from "zustand";

const getInitialTheme = () => {
  if (typeof window === "undefined") return "light";
  const stored = localStorage.getItem("clarivo_theme");
  if (stored === "dark" || stored === "light") {
    if (stored === "dark") document.documentElement.classList.add("dark");
    else document.documentElement.classList.remove("dark");
    return stored;
  }
  return "light";
};

export const useThemeStore = create((set) => ({
  theme: getInitialTheme(),
  setTheme: (theme) => {
    if (typeof window !== "undefined") {
      localStorage.setItem("clarivo_theme", theme);
      if (theme === "dark") {
        document.documentElement.classList.add("dark");
      } else {
        document.documentElement.classList.remove("dark");
      }
    }
    set({ theme });
  },
  toggleTheme: () => {
    set((state) => {
      const nextTheme = state.theme === "dark" ? "light" : "dark";
      if (typeof window !== "undefined") {
        localStorage.setItem("clarivo_theme", nextTheme);
        if (nextTheme === "dark") {
          document.documentElement.classList.add("dark");
        } else {
          document.documentElement.classList.remove("dark");
        }
      }
      return { theme: nextTheme };
    });
  },
}));
