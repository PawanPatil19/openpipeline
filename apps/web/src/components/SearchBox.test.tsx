import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { SearchHit } from "../lib/api";
import { SearchBox } from "./SearchBox";

const hits: SearchHit[] = [
  {
    kind: "model",
    node_id: "model.shop.orders",
    name: "orders",
    column: null,
    snippet: "One row per order.",
    score: 100,
  },
  {
    kind: "column",
    node_id: "model.shop.customers",
    name: "customers",
    column: "lifetime_value",
    snippet: "Total paid.",
    score: 50,
  },
];

function setup() {
  const fetchMock = vi.fn(async (url: string) => {
    const q = new URL(url, "http://x").searchParams.get("q");
    return new Response(JSON.stringify(q === "zzz" ? [] : hits), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  const onPick = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SearchBox onPick={onPick} />
    </QueryClientProvider>,
  );
  return { onPick, fetchMock };
}

afterEach(() => vi.unstubAllGlobals());

describe("SearchBox", () => {
  it("focuses with / and with Ctrl+K", async () => {
    setup();
    const input = screen.getByRole("combobox", { name: "Search models and columns" });
    expect(input).not.toHaveFocus();
    await userEvent.keyboard("/");
    expect(input).toHaveFocus();
    // The slash is not typed into the box.
    expect(input).toHaveValue("");

    (input as HTMLInputElement).blur();
    expect(input).not.toHaveFocus();
    await userEvent.keyboard("{Control>}k{/Control}");
    expect(input).toHaveFocus();
  });

  it("does not steal / while typing in the box", async () => {
    setup();
    const input = screen.getByRole("combobox");
    await userEvent.click(input);
    await userEvent.keyboard("a/b");
    expect(input).toHaveValue("a/b");
  });

  it("moves through results with the arrow keys and picks with Enter", async () => {
    const { onPick, fetchMock } = setup();
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.keyboard("order");
    const options = await screen.findAllByRole("option");
    expect(options).toHaveLength(2);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("q=order"), expect.anything());
    expect(options[0]).toHaveAttribute("aria-selected", "true");

    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getAllByRole("option")[1]).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("combobox")).toHaveAttribute(
      "aria-activedescendant",
      screen.getAllByRole("option")[1]?.id,
    );

    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{ArrowUp}");
    expect(screen.getAllByRole("option")[1]).toHaveAttribute("aria-selected", "true");

    await userEvent.keyboard("{Enter}");
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick).toHaveBeenCalledWith(hits[1]);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveValue("");
  });

  it("picks with the mouse and shows column hits as node.column", async () => {
    const { onPick } = setup();
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.keyboard("life");
    await userEvent.click(await screen.findByText("customers.lifetime_value"));
    expect(onPick).toHaveBeenCalledWith(hits[1]);
  });

  it("closes on Escape and says when nothing matches", async () => {
    const { onPick } = setup();
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.keyboard("zzz");
    expect(await screen.findByText(/Nothing matches/)).toBeInTheDocument();
    await userEvent.keyboard("{Enter}");
    expect(onPick).not.toHaveBeenCalled();

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
