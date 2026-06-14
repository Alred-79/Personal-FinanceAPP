import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";

const { apiGet, apiPut, apiDelete, toastSpy } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
  toastSpy: vi.fn(),
}));
vi.mock("@/lib/api", () => ({
  default: { get: apiGet, put: apiPut, delete: apiDelete },
}));
vi.mock("@/hooks/useToast", () => ({
  useToast: () => ({ toast: toastSpy }),
  toast: toastSpy,
}));

import { TaxTagControl } from "@/components/custom/TaxTagBadge/TaxTagControl";

const BUCKETS = [
  { key: "sch_c_18_office", label: "Office expense (Sch C line 18)",
    irs_line: "Schedule C line 18", default_deductible_bps: 10000, kind: "expense" },
  { key: "sch_c_24b_meals", label: "Meals (Sch C line 24b)",
    irs_line: "Schedule C line 24b", default_deductible_bps: 5000, kind: "expense" },
];

const EXISTING_TAG = {
  id: 1, tx_type: "expense", tx_id: 42, tax_year: 2026,
  bucket: "sch_c_18_office", bucket_label: "Office expense (Sch C line 18)",
  irs_line: "Schedule C line 18", business_personal: "business",
  deductible_bps: 10000, source: "user", note: null,
};

beforeEach(() => {
  apiGet.mockReset();
  apiPut.mockReset();
  apiDelete.mockReset();
  toastSpy.mockReset();
});
afterEach(cleanup);

describe("TaxTagControl", () => {
  it("shows the existing tag's bucket label as a chip after opening", async () => {
    apiGet.mockImplementation((url: string) => {
      if (url === "/tax/buckets/") return Promise.resolve({ data: BUCKETS });
      return Promise.resolve({ data: EXISTING_TAG }); // current tag
    });
    render(<TaxTagControl txType="expense" txId={42} />);
    // Open the popover so it lazily loads the current tag.
    fireEvent.click(screen.getByLabelText("Tax tag"));
    await waitFor(() =>
      expect(
        screen.getByText(/Office expense \(Sch C line 18\)/)
      ).toBeInTheDocument()
    );
  });

  it("loads the tag lazily — no fetch until the popover opens", () => {
    apiGet.mockResolvedValue({ data: BUCKETS });
    render(<TaxTagControl txType="expense" txId={42} />);
    // Rendered but not opened → no tag/bucket request fired.
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("removes a tag via the delete endpoint", async () => {
    apiGet.mockImplementation((url: string) => {
      if (url === "/tax/buckets/") return Promise.resolve({ data: BUCKETS });
      return Promise.resolve({ data: EXISTING_TAG });
    });
    apiDelete.mockResolvedValue({ data: {} });
    render(<TaxTagControl txType="expense" txId={42} />);
    fireEvent.click(screen.getByLabelText("Tax tag"));
    await screen.findByText("Remove");
    fireEvent.click(screen.getByText("Remove"));
    await waitFor(() =>
      expect(apiDelete).toHaveBeenCalledWith("/tax/tags/expense/42/")
    );
  });
});
