type ClassValue = string | false | null | undefined | ((...args: never[]) => string | undefined);

export function cn(...classes: ClassValue[]): string {
  return classes
    .filter(Boolean)
    .map((value) => (typeof value === "function" ? (value as () => string | undefined)() : value))
    .filter(Boolean)
    .join(" ");
}
