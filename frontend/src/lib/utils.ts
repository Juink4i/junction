export { cn } from "cn"

/** The plain <select> style the forms share. */
export const select = 'h-9 rounded-md border bg-white px-2 text-sm'
/** A number input's value: empty means no number yet. */
export const num = (s: string): number | null => (s === '' ? null : Number(s))
