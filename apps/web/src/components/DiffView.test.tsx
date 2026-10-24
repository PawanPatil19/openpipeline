import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DiffView } from "./DiffView";
import { ReviewLegend } from "./ReviewLegend";

const DIFF = `--- a/models/a.sql
+++ b/models/a.sql
@@ -1,2 +1,2 @@
 select 1
-from old_table
+from new_table
`;

describe("DiffView", () => {
  it("marks added and removed lines", () => {
    render(<DiffView diff={DIFF} />);
    expect(screen.getByText("+from new_table").getAttribute("data-kind")).toBe("add");
    expect(screen.getByText("-from old_table").getAttribute("data-kind")).toBe("del");
    expect(screen.getByText(/^@@/).getAttribute("data-kind")).toBe("hunk");
    expect(screen.getByText("select 1", { exact: false }).getAttribute("data-kind")).toBe("ctx");
  });

  it("says so when nothing changed", () => {
    render(<DiffView diff="" />);
    expect(screen.getByText("No changes in this file.")).toBeInTheDocument();
  });
});

describe("ReviewLegend", () => {
  it("explains the colours and lets you exit", async () => {
    const onExit = vi.fn();
    render(<ReviewLegend title="Add revenue" onExit={onExit} />);
    for (const label of ["New", "Changed", "Removed", "Results may change"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    await userEvent.click(screen.getByRole("button", { name: "Exit review" }));
    expect(onExit).toHaveBeenCalled();
  });
});
