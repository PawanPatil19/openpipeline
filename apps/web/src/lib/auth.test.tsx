import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../App";
import { TokenDialog } from "../components/TokenDialog";
import { ApiError, api } from "./api";
import {
  authHeaders,
  captureTokenFromUrl,
  clearToken,
  dismissTokenPrompt,
  getToken,
  isPromptingForToken,
  setToken,
} from "./auth";

afterEach(() => {
  vi.unstubAllGlobals();
  clearToken();
  dismissTokenPrompt();
  window.sessionStorage.clear();
});

describe("token storage", () => {
  it("takes ?token= from the URL, stores it, and cleans the address bar", () => {
    const replaceState = vi.fn();
    const taken = captureTokenFromUrl(
      { href: "http://localhost:8484/some/path?a=1&token=abc123&b=2#frag" },
      { replaceState },
    );
    expect(taken).toBe(true);
    expect(getToken()).toBe("abc123");
    expect(window.sessionStorage.getItem("openpipeline.token")).toBe("abc123");
    expect(replaceState).toHaveBeenCalledWith(null, "", "/some/path?a=1&b=2#frag");
    expect(authHeaders()).toEqual({ Authorization: "Bearer abc123" });
  });

  it("does nothing when there is no token in the URL", () => {
    const replaceState = vi.fn();
    expect(captureTokenFromUrl({ href: "http://localhost:8484/?a=1" }, { replaceState })).toBe(
      false,
    );
    expect(replaceState).not.toHaveBeenCalled();
    expect(getToken()).toBeNull();
    expect(authHeaders()).toEqual({});
  });

  it("removes an empty token parameter without storing anything", () => {
    const replaceState = vi.fn();
    expect(captureTokenFromUrl({ href: "http://x/?token=" }, { replaceState })).toBe(false);
    expect(replaceState).toHaveBeenCalledWith(null, "", "/");
    expect(getToken()).toBeNull();
  });

  it("falls back to memory when sessionStorage throws", () => {
    const boom = () => {
      throw new Error("blocked");
    };
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(boom);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(boom);
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(boom);
    try {
      expect(() => setToken("mem")).not.toThrow();
      expect(getToken()).toBe("mem");
      expect(() => clearToken()).not.toThrow();
      expect(getToken()).toBeNull();
    } finally {
      vi.restoreAllMocks();
    }
  });
});

function stubFetch(handler: (url: string, init?: RequestInit) => Response) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => handler(url, init));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function headersOf(call: unknown[]): Record<string, string> {
  return ((call[1] as RequestInit).headers ?? {}) as Record<string, string>;
}

describe("sending the token", () => {
  it("adds the Bearer header to writes and /api/auth, not to other reads", async () => {
    setToken("tok");
    const fetchMock = stubFetch(() => new Response("{}", { status: 200 }));
    await api.saveDocs("customers", { description: "x" });
    await api.comment("abc", "hi");
    await api.aiExplain("customers");
    await api.decide("abc", "accepted");
    await api.auth();
    await api.project();
    const calls = fetchMock.mock.calls;
    for (const call of calls.slice(0, 5)) expect(headersOf(call).Authorization).toBe("Bearer tok");
    expect(headersOf(calls[5] as unknown[]).Authorization).toBeUndefined();
    expect(headersOf(calls[0] as unknown[])["Content-Type"]).toBe("application/json");
  });

  it("sends no Authorization header when there is no token", async () => {
    const fetchMock = stubFetch(() => new Response("{}", { status: 200 }));
    await api.comment("abc", "hi");
    expect(headersOf(fetchMock.mock.calls[0] as unknown[]).Authorization).toBeUndefined();
  });

  it("opens the token prompt when a write is refused with 401, but not for reads", async () => {
    stubFetch(
      () => new Response(JSON.stringify({ detail: "A write token is required." }), { status: 401 }),
    );
    await expect(api.comment("abc", "hi")).rejects.toBeInstanceOf(ApiError);
    expect(isPromptingForToken()).toBe(true);
    dismissTokenPrompt();
    await expect(api.project()).rejects.toBeInstanceOf(ApiError);
    expect(isPromptingForToken()).toBe(false);
  });
});

function renderWith(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("TokenDialog", () => {
  it("stays hidden until a write gets a 401, then stores the pasted token", async () => {
    stubFetch(() => new Response(JSON.stringify({ detail: "no" }), { status: 401 }));
    renderWith(<TokenDialog />);
    expect(screen.queryByRole("dialog")).toBeNull();
    await expect(api.comment("abc", "hi")).rejects.toBeInstanceOf(ApiError);
    const input = await screen.findByLabelText("Write token");
    await userEvent.type(input, "  pasted-token ");
    await userEvent.click(screen.getByRole("button", { name: "Save token" }));
    expect(getToken()).toBe("pasted-token");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("can be cancelled without storing anything", async () => {
    stubFetch(() => new Response("{}", { status: 401 }));
    renderWith(<TokenDialog />);
    await expect(api.comment("abc", "hi")).rejects.toBeInstanceOf(ApiError);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(getToken()).toBeNull();
  });
});

const project = {
  name: "p",
  root: "/p",
  loaded_from: "files",
  model_count: 1,
  source_count: 0,
  warnings: [],
};
const proposal = {
  id: "abc123abc123",
  title: "Add revenue model",
  rationale: "",
  author: "claude",
  created_at: "2026-10-24T00:00:00Z",
  status: "pending",
  changes: [{ path: "models/revenue.sql", content: "select 1" }],
  comments: [],
};

function appWithAuth(auth: unknown, status = 200) {
  const responses: Record<string, unknown> = {
    "/api/project": project,
    "/api/graph": { nodes: [], edges: [] },
    "/api/rules": { rules: [], warnings: [] },
    "/api/proposals": [proposal],
    "/api/auth": auth,
  };
  const fetchMock = stubFetch((url) => {
    if (url === "/api/auth") return new Response(JSON.stringify(auth), { status });
    const body = responses[url];
    return new Response(JSON.stringify(body ?? { detail: "nope" }), { status: body ? 200 : 404 });
  });
  renderWith(<App />);
  return fetchMock;
}

describe("write modes in the app", () => {
  it("hides accept, reject and comments with a note in read-only mode", async () => {
    appWithAuth({ writes: "off", token_valid: null });
    expect(await screen.findByText(/Read-only: this server does not allow edits/)).toBeVisible();
    await userEvent.click(await screen.findByRole("button", { name: /Proposals/ }));
    expect(await screen.findByText("Add revenue model")).toBeInTheDocument();
    expect(screen.getByText(/does not allow accepting or rejecting/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept and write files" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Send feedback" })).toBeNull();
  });

  it("keeps the buttons and asks for a token in token mode without a valid one", async () => {
    appWithAuth({ writes: "token", token_valid: false });
    expect(await screen.findByText(/Changes need a write token/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: /Proposals/ }));
    expect(await screen.findByRole("button", { name: "Accept and write files" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Enter token" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("shows no notice in open mode", async () => {
    appWithAuth({ writes: "open", token_valid: null });
    await screen.findByText(/p · 1 models/);
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("treats a missing /api/auth as open", async () => {
    appWithAuth({ detail: "not found" }, 404);
    await userEvent.click(await screen.findByRole("button", { name: /Proposals/ }));
    expect(await screen.findByRole("button", { name: "Accept and write files" })).toBeEnabled();
    expect(screen.queryByRole("note")).toBeNull();
  });
});
