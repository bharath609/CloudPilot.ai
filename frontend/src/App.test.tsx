import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import App from "./App";
import { installMockApi } from "./test/mockApi";

describe("application shell", () => {
  it("renders navigation and the complete overview from API data", async () => {
    installMockApi();
    render(<App />);

    expect(screen.getByRole("navigation", { name: /main navigation/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /cost explorer/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /audit/i })).toBeInTheDocument();

    // The sample notice is a first-class part of the chrome.
    expect(await screen.findByText("Synthetic demo data is loaded.")).toBeInTheDocument();
    expect(screen.getAllByText("Synthetic sample data").length).toBeGreaterThan(0);

    // Exact decimal totals, not float artefacts.
    expect((await screen.findAllByText("1,531.31 USD")).length).toBeGreaterThan(0);
    expect(screen.getByText("+50.00%")).toBeInTheDocument();
    expect(screen.getByText("765.02 USD")).toBeInTheDocument();

    // Freshness facts from /api/filters.
    expect(screen.getAllByText(/utilization_sample\.csv/).length).toBeGreaterThan(0);
    expect(screen.getByText(/4 catalogue entr/)).toBeInTheDocument();

    // Empty findings are explained rather than invented.
    expect(screen.getByText("No findings yet")).toBeInTheDocument();
  });
});
