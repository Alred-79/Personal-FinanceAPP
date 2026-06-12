import { Button } from "@/components/ui/button";
import { useEffect, useState } from "react";
import { DayCheckboxProps } from "@/types";

function DayCheckbox({ value, selected, onChange }: DayCheckboxProps) {
  const [isSelected, setIsSelected] = useState(selected ?? false);

  // Sync with external `selected` prop so the parent can drive reset/rerender.
  useEffect(() => {
    setIsSelected(selected ?? false);
  }, [selected]);

  const handleClick = () => {
    const next = !isSelected;
    setIsSelected(next);
    onChange(value, next);
  };

  return (
    <Button
      type="button"
      variant={isSelected ? "default" : "secondary"}
      className={
        isSelected
          ? "border-gold bg-gold text-background hover:bg-gold/90"
          : "text-muted-foreground hover:bg-wash"
      }
      onClick={handleClick}
    >
      {value}
    </Button>
  );
}

export default DayCheckbox;
