import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Tailwind-aware className combiner. Standard shadcn helper — merges
 * conditional class lists and lets later tokens win on conflict
 * (so `cn("px-2", isLarge && "px-4")` resolves to `px-4`, not both).
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
