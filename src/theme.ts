import { ref } from "vue";

export type ThemeMode = "system" | "light" | "dark";
const key = "silvercode.account.theme";
const system = window.matchMedia("(prefers-color-scheme: dark)");
const valid = (value: unknown): value is ThemeMode =>
  value === "light" || value === "dark" || value === "system";

function readMode(): ThemeMode {
  try {
    const saved = localStorage.getItem(key);
    return valid(saved) ? saved : "system";
  } catch { return "system"; }
}

export const themeMode = ref<ThemeMode>(readMode());

function applyTheme() {
  const dark = themeMode.value === "dark" || (themeMode.value === "system" && system.matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#14121c" : "#f8f8fb");
}

export function setThemeMode(mode: ThemeMode) {
  themeMode.value = mode;
  try { localStorage.setItem(key, mode); } catch { /* Private browsing can deny storage. */ }
  applyTheme();
}

system.addEventListener("change", applyTheme);
window.addEventListener("storage", (event) => {
  if (event.key !== key && event.key !== null) return;
  themeMode.value = readMode();
  applyTheme();
});
applyTheme();
