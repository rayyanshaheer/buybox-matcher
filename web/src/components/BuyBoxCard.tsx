/**
 * BuyBoxCard — renders an extracted Buy_Box as a set of labeled chips.
 *
 * Per the design ("Frontend Components" → BuyBoxCard) and Requirement 12.3,
 * each of the nine Buy_Box fields (markets, strategy, property_type,
 * price_min, price_max, arv_pct_max, min_beds, min_baths, condition) is shown
 * as a labeled chip. Fields whose value is absent — `null`, or an empty
 * `markets` array — render as a muted "not specified" chip so the viewer can
 * see that the field was simply not present in the source message rather than
 * missing from the display (the null-for-absent rule from extraction).
 *
 * This component is presentational and pure: it takes a `BuyBox` prop (the
 * shared wire type from `web/src/types.ts`) and renders, performing no I/O.
 */
import type { BuyBox } from "../types";

interface BuyBoxCardProps {
  /** The structured purchase criteria to display. */
  buyBox: BuyBox;
}

/** Humanize an enum token like `fix_and_flip` into `Fix and flip`. */
function humanizeEnum(value: string): string {
  const spaced = value.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Format an integer dollar amount as `$120,000`. */
function formatCurrency(value: number): string {
  return `$${value.toLocaleString("en-US")}`;
}

/**
 * One labeled chip. When `value` is `null` the chip renders in a muted style
 * with the text "not specified" (Requirement 12.3).
 */
function Chip({ label, value }: { label: string; value: string | null }) {
  const specified = value !== null;
  return (
    <div
      className={`inline-flex flex-col rounded-md border px-3 py-1.5 text-sm ${
        specified
          ? "border-gray-300 bg-white text-gray-900"
          : "border-dashed border-gray-300 bg-gray-50 text-gray-400"
      }`}
    >
      <span className="text-[11px] font-medium uppercase tracking-wide text-gray-500">
        {label}
      </span>
      <span className={specified ? "font-medium" : "italic"}>
        {specified ? value : "not specified"}
      </span>
    </div>
  );
}

export default function BuyBoxCard({ buyBox }: BuyBoxCardProps) {
  const marketsValue =
    buyBox.markets.length > 0 ? buyBox.markets.join(", ") : null;

  return (
    <div className="flex flex-wrap gap-2" aria-label="Extracted buy box">
      <Chip label="Markets" value={marketsValue} />
      <Chip
        label="Strategy"
        value={buyBox.strategy === null ? null : humanizeEnum(buyBox.strategy)}
      />
      <Chip
        label="Property type"
        value={
          buyBox.property_type === null
            ? null
            : humanizeEnum(buyBox.property_type)
        }
      />
      <Chip
        label="Price min"
        value={buyBox.price_min === null ? null : formatCurrency(buyBox.price_min)}
      />
      <Chip
        label="Price max"
        value={buyBox.price_max === null ? null : formatCurrency(buyBox.price_max)}
      />
      <Chip
        label="ARV % max"
        value={buyBox.arv_pct_max === null ? null : `${buyBox.arv_pct_max}%`}
      />
      <Chip
        label="Min beds"
        value={buyBox.min_beds === null ? null : String(buyBox.min_beds)}
      />
      <Chip
        label="Min baths"
        value={buyBox.min_baths === null ? null : String(buyBox.min_baths)}
      />
      <Chip
        label="Condition"
        value={buyBox.condition === null ? null : humanizeEnum(buyBox.condition)}
      />
    </div>
  );
}
