import { useCallback, useState } from "react";
import { ApiError } from "@/lib/api";
import { useCountdown } from "./useCountdown";

/** The last API error and its Retry-After cooldown (seconds left, 0 when none). */
export function useApiError() {
  const [error, setError] = useState<ApiError | null>(null);
  const [deadline, setDeadline] = useState<number | null>(null);
  const cooldown = useCountdown(deadline);

  const fail = useCallback((err: unknown) => {
    const apiError =
      err instanceof ApiError ? err : new ApiError("server", "Something went wrong. Please try again.");
    setError(apiError);
    setDeadline(apiError.retryAfter ? Date.now() + apiError.retryAfter * 1000 : null);
  }, []);

  const clear = useCallback(() => {
    setError(null);
    setDeadline(null);
  }, []);

  return { error, cooldown, fail, clear };
}
