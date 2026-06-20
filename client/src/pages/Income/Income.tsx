import PageHeader from "@/components/layout/PageHeader";
import { Reveal, RevealItem } from "@/components/motion/Reveal";
import IncomeVolatility from "@/components/custom/IncomeVolatility/IncomeVolatility";

/**
 * The Income surface (W5 freelancer wedge). Nav presence is gated by the server
 * freelancer flag (freelancerOnly); the route always exists and the inner
 * component self-handles the disabled (404) state.
 */
export default function Income() {
  return (
    <>
      <PageHeader
        title="Income"
        description="How steady your earnings are — and how much to hold back so Safe-to-Spend rides out a lean month."
        reference="Form XVI · Income Smoothing"
      />
      <Reveal>
        <RevealItem>
          <IncomeVolatility />
        </RevealItem>
      </Reveal>
    </>
  );
}
