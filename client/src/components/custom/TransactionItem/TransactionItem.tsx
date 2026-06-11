import { Transaction } from "@/types";
import {
  House,
  Utensils,
  Bus,
  Droplet,
  Drama,
  Trash2,
  Briefcase,
  Hammer,
  Store,
  ArrowLeftRight,
  Plane,
  Shapes,
} from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useIsMobile } from "@/hooks/responsive";
import styles from "./TransactionItem.module.css";

function TransactionItem({
  transaction,
  onDelete,
  style,
}: {
  transaction: Transaction;
  onDelete: (() => void) | null;
  style?: React.CSSProperties;
}) {
  const [isHovered, setIsHovered] = useState(false);
  const isMobile = useIsMobile();
  const [isSelected, setIsSelected] = useState(false);

  const handleClick = () => {
    if (isMobile) {
      setIsSelected(!isSelected);
    }
  };

  return (
    <div
      style={style}
      className={styles.container}
      onMouseEnter={() => !isMobile && setIsHovered(true)}
      onMouseLeave={() => !isMobile && setIsHovered(false)}
      onClick={handleClick}
    >
      <div className={styles.flexRow}>
        {transaction.category === "Housing" && (
          <House style={{ color: transaction.backgroundColor }} />
        )}
        {(transaction.category === "Food" ||
          transaction.category === "Food and Drink") && (
          <Utensils style={{ color: transaction.backgroundColor }} />
        )}
        {transaction.category === "Transportation" && (
          <Bus style={{ color: transaction.backgroundColor }} />
        )}
        {transaction.category === "Utilities" && (
          <Droplet style={{ color: transaction.backgroundColor }} />
        )}
        {(transaction.category === "Entertainment" ||
          transaction.category === "Recreation") && (
          <Drama style={{ color: transaction.backgroundColor }} />
        )}
        {transaction.category === "Work" && (
          <Briefcase style={{ color: transaction.backgroundColor }} />
        )}
        {transaction.category === "Service" && (
          <Hammer style={{ color: transaction.backgroundColor }} />
        )}
        {transaction.category === "Shops" && (
          <Store style={{ color: transaction.backgroundColor }} />
        )}
        {transaction.category === "Transfer" && (
          <ArrowLeftRight style={{ color: transaction.backgroundColor }} />
        )}
        {transaction.category === "Travel" && (
          <Plane style={{ color: transaction.backgroundColor }} />
        )}
        {transaction.category === "Other" && (
          <Shapes style={{ color: transaction.backgroundColor }} />
        )}
        <div className={styles.flexCol}>
          <p className={styles.titleText}>{transaction.title}</p>
          <p className={styles.dateText}>{transaction.date}</p>
        </div>
      </div>
      <div className={styles.amountContainer}>
        <p
          className={styles.amountText}
          style={{
            color:
              transaction.type === "income"
                ? "hsl(var(--success))"
                : "hsl(var(--destructive))",
          }}
        >
          {transaction.type === "income" ? "+" : "-"}$
          {transaction.amount.toFixed(2)}
        </p>
        {onDelete !== null && ((!isMobile && isHovered) || (isMobile && isSelected)) && (
          <Button
            variant="ghost"
            size="icon"
            className={styles.deleteButton}
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
              if (isMobile) {
                setIsSelected(false);
              }
            }}
          >
            <Trash2 className="text-destructive" size={24} />
          </Button>
        )}
      </div>
    </div>
  );
}

export default TransactionItem;
