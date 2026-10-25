import { useQuery } from "@tanstack/react-query";
import { type AuthInfo, api, type WriteMode } from "./api";

const OPEN: AuthInfo = { writes: "open", token_valid: null };

/**
 * How writes are protected on the server. If the server cannot say (an older server,
 * or the static demo), assume writes are allowed and let the server refuse them.
 */
export function useAuth(): { mode: WriteMode; canWrite: boolean; tokenValid: boolean | null } {
  const auth = useQuery({
    queryKey: ["auth"],
    queryFn: () => api.auth().catch(() => OPEN),
  });
  const mode = auth.data?.writes ?? "open";
  return { mode, canWrite: mode !== "off", tokenValid: auth.data?.token_valid ?? null };
}
