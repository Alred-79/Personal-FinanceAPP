import { describe, it, expect, afterEach } from "vitest";
import { render, screen, within, cleanup, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { SpecimenSheet } from "@/pages/Landing/sections/SpecimenSheet";
import { Security } from "@/pages/Landing/sections/Security";
import { AgentReadingRoom } from "@/pages/Landing/sections/AgentReadingRoom";
import {
  IMPACT,
  NOT_CLAIMED,
  PLATES,
  TIERS,
  type Citation,
} from "@/pages/Landing/sections/specimen/specimenData";

/**
 * The Specimen Sheet is the page's honesty surface: every sentence on it is
 * supposed to survive a senior engineer opening the cited file. Most of what is
 * asserted below is therefore about the CLAIMS, not the pixels — the citation
 * shape, the tier contract (a Level II or III entry without its precondition is
 * a lie by omission and must fail the build), and the gap no tier may absorb.
 */

afterEach(cleanup);

const ALL_CITATIONS: Citation[] = [
  ...PLATES.flatMap((p) => p.proof),
  ...TIERS.flatMap((t) => t.entries.flatMap((e) => e.proof)),
  ...NOT_CLAIMED.proof,
];

const CLAIM_COUNT = PLATES.length + TIERS.reduce((n, t) => n + t.entries.length, 0);

/** Everything the section renders as prose, lowercased. */
function sheetText() {
  const { container } = render(<SpecimenSheet />);
  return (container.textContent ?? "").toLowerCase();
}

describe("The Specimen Sheet", () => {
  it("frames itself as the note's own list of anti-forgery features", () => {
    render(<SpecimenSheet />);
    expect(
      screen.getByRole("heading", { name: /Every note prints the reasons it can’t be forged/i })
    ).toBeInTheDocument();
    expect(screen.getByText(/would rather open the files/i)).toBeInTheDocument();
  });

  it("presents exactly five numbered callouts, as tabs into one reading", () => {
    render(<SpecimenSheet />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(PLATES.length);
    expect(tabs).toHaveLength(5);
    expect(screen.getAllByRole("tablist")).toHaveLength(1);

    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(tabs[0]).toHaveAttribute("tabindex", "0");
    for (const t of tabs.slice(1)) {
      expect(t).toHaveAttribute("aria-selected", "false");
      expect(t).toHaveAttribute("tabindex", "-1");
    }
    for (const p of PLATES) {
      expect(screen.getByRole("tab", { name: new RegExp(p.feature, "i") })).toBeInTheDocument();
    }
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "spx-tab-1");
  });

  it("opens a callout into its threat, its enforcement, and its proof", () => {
    render(<SpecimenSheet />);
    fireEvent.click(screen.getByRole("tab", { name: /The two doorways/i }));

    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveAttribute("aria-labelledby", "spx-tab-2");
    expect(within(panel).getByText("The threat")).toBeInTheDocument();
    expect(within(panel).getByText("The enforcement")).toBeInTheDocument();
    expect(within(panel).getByText("The proof")).toBeInTheDocument();
    expect(
      within(panel).getByText(/exactly two files: vault\.py, which reads, and actions\.py/i)
    ).toBeInTheDocument();
    expect(
      within(panel).getByText("test_db_doors_are_exactly_the_sanctioned_set")
    ).toBeInTheDocument();
  });

  /**
   * The capability↔resource gate is the sheet's own argument turned on itself:
   * it was the one place enforcement sat ABOVE the layer at which the mistake
   * would be made. It therefore has to appear as an unconditional Level I
   * callout — no flag, no deployment precondition — and it has to carry the
   * structural test, not just the three cross-resource denials, because that is
   * what stops the guard rotting as resources are added.
   */
  it("prints the capability↔resource binding as an unconditional callout", () => {
    render(<SpecimenSheet />);
    const ward = PLATES.find((p) => p.feature === "The ward on each door");
    expect(ward, "the scope gate must be one of the numbered callouts").toBeTruthy();
    // A callout is Level I by construction — it must not have crept into a
    // conditional tier, and no tier entry may claim it behind a gate.
    for (const t of TIERS) {
      for (const e of t.entries) expect(e.title).not.toMatch(/ward on each door/i);
    }

    fireEvent.click(screen.getByRole("tab", { name: /The ward on each door/i }));
    const panel = screen.getByRole("tabpanel");
    // fail-closed is the load-bearing property, not "we check the scope"
    expect(panel.textContent).toMatch(/an absent resource is denied/i);
    expect(panel.textContent).toMatch(/before it opens a database session/i);
    // the caveat that keeps this honest: it was never reachable from outside
    expect(panel.textContent).toMatch(/nothing outside could reach it/i);
    // the one deliberate exception is named, not glossed
    expect(panel.textContent).toMatch(/ping/);
    // the denial is audited, with the decisions the code actually records
    expect(panel.textContent).toContain("deny:missing_scope");
    expect(panel.textContent).toContain("deny:unknown_resource");
    expect(within(panel).getByText("_RESOURCE_SCOPES")).toBeInTheDocument();
    expect(
      within(panel).getByText("test_every_dispatchable_resource_has_a_scope_decision")
    ).toBeInTheDocument();
  });

  it("moves between callouts from the keyboard, and wraps", () => {
    render(<SpecimenSheet />);
    const tabs = screen.getAllByRole("tab");
    tabs[0].focus();

    fireEvent.keyDown(tabs[0], { key: "ArrowRight" });
    expect(screen.getAllByRole("tab")[1]).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "spx-tab-2");

    fireEvent.keyDown(screen.getAllByRole("tab")[1], { key: "ArrowLeft" });
    fireEvent.keyDown(screen.getAllByRole("tab")[0], { key: "ArrowLeft" });
    expect(screen.getAllByRole("tab")[4]).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(screen.getAllByRole("tab")[4], { key: "Home" });
    expect(screen.getAllByRole("tab")[0]).toHaveAttribute("aria-selected", "true");
  });

  /* ── the tier contract ────────────────────────────────────────────────── */

  it("grades every mechanism into one of three verification levels", () => {
    render(<SpecimenSheet />);
    expect(TIERS.map((t) => t.numeral)).toEqual(["I", "II", "III"]);
    for (const t of TIERS) {
      expect(
        screen.getByRole("heading", { name: new RegExp(`Level ${t.numeral}\\s*${t.name}`, "i") })
      ).toBeInTheDocument();
      for (const e of t.entries) {
        expect(screen.getByText(e.title)).toBeInTheDocument();
      }
    }
    // The four callouts are Level I too — said on the sheet, not just implied.
    expect(screen.getByText(/the five strongest, callout by callout/i)).toBeInTheDocument();
    expect(TIERS[0].rule).toMatch(/the five numbered callouts above are Level I too/i);
  });

  it("carries enough of the surface to be worth reading", () => {
    // The audit found 42 mechanisms; the sheet is a selection, not a dump — but
    // a four-item sheet under-reports what is actually enforced.
    expect(CLAIM_COUNT).toBeGreaterThanOrEqual(15);
    expect(CLAIM_COUNT).toBeLessThanOrEqual(22);
    expect(ALL_CITATIONS.length).toBeGreaterThanOrEqual(40);
  });

  it("REFUSES a conditional claim that does not print its own precondition", () => {
    // This is the whole reason the tier system is honest rather than cosmetic.
    for (const t of TIERS) {
      for (const e of t.entries) {
        if (t.id === "i") {
          expect(e.gate, `Level I entry "${e.title}" must be unconditional`).toBeUndefined();
        } else {
          expect(e.gate, `Level ${t.numeral} entry "${e.title}" must name its gate`).toBeTruthy();
          expect(e.gate!.length).toBeGreaterThan(30);
        }
      }
    }
  });

  it("renders each gate inside its entry, ahead of the mechanism", () => {
    render(<SpecimenSheet />);
    for (const t of TIERS.filter((x) => x.id !== "i")) {
      for (const e of t.entries) {
        const row = screen.getByText(e.title).closest(".spx-row");
        expect(row, e.title).not.toBeNull();
        const gate = row!.querySelector(".spx-gate");
        expect(gate, `no gate rendered for "${e.title}"`).not.toBeNull();
        expect(gate!.textContent).toContain(e.gate!.slice(0, 40));
        // The precondition is read before the mechanism, not after it.
        const body = row!.querySelector(".spx-row__text")!;
        expect(gate!.compareDocumentPosition(body) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      }
    }
  });

  it("names the actual flags for everything that ships dark", () => {
    render(<SpecimenSheet />);
    const three = screen.getByText(/Under the microscope/i).closest(".spx-tier")!;
    expect(three.textContent).toContain("MCP_ENABLED=false");
    expect(three.textContent).toContain("mcp_propose_enabled");
    expect(three.textContent).toContain("rail_origination_enabled");
    const two = screen.getByText(/Under the lamp/i).closest(".spx-tier")!;
    expect(two.textContent).toContain("ENABLE_RLS=true");
    expect(two.textContent).toContain("TRUST_PROXY");
    expect(two.textContent).toMatch(/not a superuser/i);
  });

  /* ── the figures ─────────────────────────────────────────────────────── */

  it("prints measured figures, with no invented precision", () => {
    const { container } = render(<SpecimenSheet />);
    // Scoped to the figure band: "1" and "3" are also callout numerals.
    const band = within(container.querySelector(".spx-figures") as HTMLElement);
    expect(IMPACT).toHaveLength(4);
    for (const f of IMPACT) {
      expect(band.getByText(f.value)).toBeInTheDocument();
      // No rounded-off marketing numbers: nothing ends in "+" or "~".
      expect(f.value).not.toMatch(/[+~]/);
      expect(f.value).toMatch(/^[\d,]+(\s\/\s[\d,]+)?$/);
    }
    expect(band.getByText(/security mechanisms audited/i)).toBeInTheDocument();
    // Two docstrings that described enforcement the code did not perform have now
    // been made true, not two-thirds of one. The caption has to say which is which.
    expect(band.getByText("4")).toBeInTheDocument();
    expect(
      band.getByText(/two by building the enforcement the docstring described, two by narrowing/i)
    ).toBeInTheDocument();
    // The test counts are the two the runner actually printed, not a headline.
    expect(band.getByText("1,573 / 1,590")).toBeInTheDocument();
  });

  /* ── the honesty contract ─────────────────────────────────────────────── */

  it("cites file paths and symbol NAMES, never line numbers", () => {
    for (const c of ALL_CITATIONS) {
      expect(c.path).not.toMatch(/:\d+/);
      expect(c.symbol ?? "").not.toMatch(/:\d+/);
      expect(c.path).toMatch(/^server\/.+\.py$/);
      if (c.symbol) {
        // A test name, a callable, or a module constant — never a line, never a range.
        expect(c.symbol).toMatch(
          /^(test_[a-z0-9_]+|[A-Z][A-Z0-9_]+|[A-Za-z_][A-Za-z0-9_.]*(\(\))?)$/
        );
      }
      if (c.kind === "test") expect(c.path).toContain("/tests/");
      if (c.kind === "migration") expect(c.path).toContain("/migrations/");
    }
  });

  it("renders the citations it holds", () => {
    render(<SpecimenSheet />);
    fireEvent.click(screen.getByRole("tab", { name: /The serial register/i }));
    expect(
      screen.getByText("test_rewriting_a_denial_into_an_allow_is_blocked")
    ).toBeInTheDocument();
    expect(screen.getByText("mcp_audit_log_append_only()")).toBeInTheDocument();
    expect(screen.getByText("TENANT_TABLES")).toBeInTheDocument();
    expect(screen.getByText("test_preauth_throttle_skips_db")).toBeInTheDocument();
    expect(screen.getByText("test_execute_absent_from_mcp_and_assistant_surface")).toBeInTheDocument();
  });

  it("never lets a tier absorb the gap that has no tier", () => {
    const text = sheetText();
    expect(text).toContain("performs no redaction");
    expect(text).toContain(NOT_CLAIMED.head.toLowerCase());
    // Explicitly not reframed as "coming soon behind a flag".
    expect(text).toContain("there is no flag that turns this on");
    expect(text).not.toMatch(/strips (ssn|emails|card)/);
    expect(text).not.toMatch(/scrubb?(ed|ing) before (it |they )?reach/);
  });

  it("never sells a conditional control as an unconditional one", () => {
    const text = sheetText();
    // Row-level security, both rate limiters and the write door all appear —
    // and every one of them appears alongside the condition that holds it.
    expect(text).toContain("row-level security");
    expect(text).toMatch(/lives in memory in a single process/);
    expect(text).toMatch(/\.env\.example both ship false/);
    expect(text).not.toMatch(/isolation is enforced in the database\b(?!.*needs postgres)/);
    expect(text).not.toMatch(/rate.?limited to \d/);
    expect(text).not.toMatch(/the agent can (execute|move money|pay)/);
  });

  it("scopes the screened-text entry to the in-app assistant, not the agent path", () => {
    render(<SpecimenSheet />);
    const row = screen.getByText(/Text the model writes is screened/i).closest(".spx-row");
    expect(row).not.toBeNull();
    expect(row!.textContent).toMatch(/the in-app assistant/i);
  });
});

describe("The claims the Specimen Sheet has to be able to stand behind", () => {
  it("keeps the Vault's PII claim fenced to the in-app assistant", () => {
    render(<Security />);
    const claim = screen.getByText(/a deterministic filter strips SSNs/i);
    expect(claim.textContent).toMatch(/before data reaches the in-app assistant/i);
    expect(claim.textContent).toMatch(/not an outside AI you connect yourself/i);
  });

  it("promises only the requests that are actually persisted", () => {
    render(
      <MemoryRouter>
        <AgentReadingRoom />
      </MemoryRouter>
    );
    expect(screen.getByText(/inspect every request your key makes/i)).toBeInTheDocument();
  });
});
