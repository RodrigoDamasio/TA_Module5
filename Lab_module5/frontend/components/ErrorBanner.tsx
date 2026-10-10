import type { ApiError } from "@/lib/api";
import { formatDuration } from "@/lib/format";

interface Props {
  error: ApiError;
  cooldown: number; // seconds left of Retry-After
  actions?: { label: string; onClick: () => void }[];
}

export default function ErrorBanner({ error, cooldown, actions = [] }: Props) {
  return (
    <div
      role="alert"
      className="space-y-2 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100"
    >
      <p className="font-medium">{error.message}</p>
      {error.fieldErrors.length > 0 && (
        <ul className="list-disc pl-5">
          {error.fieldErrors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {cooldown > 0 && <p>You can try again in {formatDuration(cooldown)}.</p>}
      {actions.length > 0 && (
        <div className="flex flex-wrap gap-3">
          {actions.map((a) => (
            <button key={a.label} type="button" onClick={a.onClick} className="font-medium underline">
              {a.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
