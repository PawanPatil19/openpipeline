import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type GraphNode } from "../lib/api";

const DEFAULT_HINT = "Install DuckDB to preview rows: pip install 'openpipeline[preview]'";

function cell(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

/** A collapsible preview of a few rows, run on local sample data. Models only. */
export function SampleRows({ node }: { node: GraphNode }) {
  const [open, setOpen] = useState(false);
  const isModel = node.kind === "model";
  const status = useQuery({
    queryKey: ["sample-status"],
    queryFn: api.sampleStatus,
    enabled: isModel,
  });
  const duckdb = status.data?.duckdb === true;
  const sample = useQuery({
    queryKey: ["sample", node.id],
    queryFn: () => api.sample(node.id),
    enabled: isModel && open && duckdb,
    retry: false,
  });

  if (!isModel || !status.data) return null;

  if (!duckdb) {
    return (
      <section className="sample" aria-label="Sample rows">
        <h3>Sample rows</h3>
        <p className="muted">{status.data.install_hint ?? DEFAULT_HINT}</p>
      </section>
    );
  }

  const error = sample.data?.error;
  return (
    <section className="sample" aria-label="Sample rows">
      <h3>
        <button
          type="button"
          className="sample__toggle"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          <span aria-hidden="true">{open ? "▾" : "▸"}</span> Sample rows
        </button>
      </h3>
      {open && sample.isPending && <p className="muted">Running the model on sample data…</p>}
      {open && sample.isError && (
        <p className="error">Could not load sample rows: {sample.error.message}</p>
      )}
      {open && error && (
        <div className="warn" role="status">
          <p>{error.message}</p>
          {error.missing_table && (
            <p>
              Add <code>sample_data/{error.missing_table}.csv</code> to preview this model.
            </p>
          )}
        </div>
      )}
      {open && sample.data && !error && (
        <>
          <div className="sample__scroll">
            <table className="sample__table">
              <thead>
                <tr>
                  {sample.data.columns.map((c) => (
                    <th key={c} scope="col">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sample.data.rows.map((row, i) => (
                  // Rows have no identity of their own, so the index is the key.
                  // biome-ignore lint/suspicious/noArrayIndexKey: sample rows are static
                  <tr key={i}>
                    {row.map((v, j) => (
                      // biome-ignore lint/suspicious/noArrayIndexKey: columns are positional
                      <td key={j}>{cell(v)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted">
            {sample.data.rows.length === 0
              ? "The model returned no rows on the sample data."
              : `Showing up to ${sample.data.row_limit} rows from local sample data.`}
          </p>
        </>
      )}
    </section>
  );
}
