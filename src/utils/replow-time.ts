export function localTime(value: string): string {
  if (!value) return "—";
  const normalized = value.replace(" ", "T");
  const date = new Date(
    /[zZ]|[+-]\\d{2}:?\\d{2}$/.test(normalized) ? normalized : normalized + "Z"
  );
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "Asia/Shanghai"
      }).format(date);
}
