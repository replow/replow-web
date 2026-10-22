import { storageLocal } from "@pureadmin/utils";

export const MIRO_PRIMARY = "#7760C9";
export const MIRO_DARK_PRIMARY = "#AF9AF4";
export const MIRO_ACCENT = "#4F95BD";
export const MIRO_AVATAR = "https://cdn.replow.org/replow-org/images/tx.jpg";
export const MIRO_WALLPAPER = "https://cdn.replow.org/replow-org/images/bg.jpg";

/** Replace the previous brand once, without clearing login or user preferences. */
export function migrateMiroBrand(config: PlatformConfigs) {
  document.documentElement.dataset.miroBrand = "v1";
  const storage = storageLocal();
  const namespace = config.ResponsiveStorageNameSpace ?? "responsive-";
  const revisionKey = namespace + "miro-brand";
  if (storage.getItem<string>(revisionKey) === "v1") return;
  const layout = storage.getItem<StorageConfigs>(namespace + "layout");
  if (layout) {
    storage.setItem(namespace + "layout", {
      ...layout,
      epThemeColor: MIRO_PRIMARY,
      theme: layout.darkMode ? "default" : "light",
      themeColor: "light"
    });
  }
  storage.setItem(revisionKey, "v1");
}

/** Keep primary actions readable when users choose another theme color. */
export function primaryForeground(color: string) {
  if (!/^#[0-9a-f]{6}$/i.test(color)) return "#ffffff";
  const values = [1, 3, 5].map(index => {
    const value = parseInt(color.slice(index, index + 2), 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  const luminance =
    values[0] * 0.2126 + values[1] * 0.7152 + values[2] * 0.0722;
  return luminance > 0.179 ? "#17152C" : "#ffffff";
}
