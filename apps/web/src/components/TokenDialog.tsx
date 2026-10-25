import { useQueryClient } from "@tanstack/react-query";
import { useState, useSyncExternalStore } from "react";
import {
  dismissTokenPrompt,
  isPromptingForToken,
  setToken,
  subscribeTokenPrompt,
} from "../lib/auth";

/** Asks for the write token after the server refused a change with 401. */
export function TokenDialog() {
  const open = useSyncExternalStore(subscribeTokenPrompt, isPromptingForToken);
  const queryClient = useQueryClient();
  const [value, setValue] = useState("");
  if (!open) return null;

  const save = () => {
    if (value.trim() === "") return;
    setToken(value.trim());
    setValue("");
    dismissTokenPrompt();
    void queryClient.invalidateQueries({ queryKey: ["auth"] });
  };

  return (
    <div className="dialog-backdrop">
      <form
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="token-title"
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
      >
        <h2 id="token-title">Enter the write token</h2>
        <p className="muted">
          This server needs a token to save changes. Paste the one printed when it started, or open
          the link it printed. Then try again.
        </p>
        <label>
          <span className="visually-hidden">Write token</span>
          <input
            type="password"
            autoComplete="off"
            placeholder="Paste the token"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </label>
        <div className="actions">
          <button type="submit" className="primary" disabled={value.trim() === ""}>
            Save token
          </button>
          <button type="button" onClick={dismissTokenPrompt}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
