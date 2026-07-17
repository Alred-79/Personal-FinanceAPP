import { Guilloche } from "@/components/engraving/Guilloche";

/**
 * A static engraved field. It keeps the Ledger's physical identity without the
 * WebGL, particles, and contrast loss of the former full-screen backdrop.
 */
export function Backdrop() {
  return (
    <div className="decision-backdrop" aria-hidden>
      <div className="decision-backdrop__hero">
        <Guilloche size={820} rings={8} seed={421018 % 99991} />
      </div>
      <div className="decision-backdrop__answer">
        <Guilloche size={520} rings={7} seed={180304} />
      </div>
    </div>
  );
}
