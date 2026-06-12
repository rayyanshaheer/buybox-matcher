/**
 * PropertyForm — the property deal input form for the Match screen.
 *
 * Per the design ("Frontend Components" → PropertyForm) and Requirements
 * 13.1, 13.2, 13.3 it provides:
 *  - text inputs for `address` and `city`,
 *  - numeric inputs for `price`, `arv`, `beds`, and `baths`,
 *  - selection controls for `property_type` and `condition` (13.1).
 *
 * While both `price` and `arv` are greater than 0 it displays the live
 * auto-computed Deal_ARV_Pct (price / arv * 100, rounded to one decimal),
 * reusing the shared `computeArvPct` helper (13.2). When `arv` is empty or 0
 * the ARV% display is suppressed; on submit in that state a validation
 * message — "arv must be greater than 0" — is shown (13.3).
 *
 * The component owns its field state internally and exposes the assembled
 * `PropertyInput` to its parent through the `onSubmit` callback, so MatchPage
 * (Task 11.3) can wire submission to the `/match` endpoint without reaching
 * into the form's internals.
 */
import { useMemo, useState, type FormEvent } from "react";
import type { Condition, PropertyInput, PropertyType } from "../types";
import { computeArvPct } from "../lib/helpers";

interface PropertyFormProps {
  /**
   * Called with the assembled, validated `PropertyInput` when the user submits
   * the form and `arv` is greater than 0. MatchPage wires this to `/match`.
   */
  onSubmit: (property: PropertyInput) => void;
  /**
   * When true the submit control is disabled and shows a busy label (e.g. while
   * a match request is in flight). Supplied by the parent (Task 11.3).
   */
  submitting?: boolean;
  /** Label for the submit button. Defaults to "Find Buyers". */
  submitLabel?: string;
  /** Optional initial values to pre-fill the form (e.g. for demo mode). */
  initialValues?: Partial<{
    address: string;
    city: string;
    price: string;
    arv: string;
    beds: string;
    baths: string;
    propertyType: PropertyType | "";
    condition: Condition | "";
  }>;
}

const PROPERTY_TYPES: PropertyType[] = [
  "single_family",
  "multi_family",
  "condo",
  "land",
];

const CONDITIONS: Condition[] = [
  "distressed",
  "light_rehab",
  "turnkey",
  "any",
];

/** Humanize an enum token like `single_family` into `Single family`. */
function humanizeEnum(value: string): string {
  const spaced = value.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * Parse a numeric text field into a number, or `null` when blank/unparseable.
 * Used for the nullable `beds`/`baths` fields and for the required price/arv
 * fields (where `null` means "not yet entered").
 */
function parseNumeric(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") {
    return null;
  }
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

export default function PropertyForm({
  onSubmit,
  submitting = false,
  submitLabel = "Find Buyers",
  initialValues,
}: PropertyFormProps) {
  const [address, setAddress] = useState(initialValues?.address ?? "");
  const [city, setCity] = useState(initialValues?.city ?? "");
  const [price, setPrice] = useState(initialValues?.price ?? "");
  const [arv, setArv] = useState(initialValues?.arv ?? "");
  const [beds, setBeds] = useState(initialValues?.beds ?? "");
  const [baths, setBaths] = useState(initialValues?.baths ?? "");
  const [propertyType, setPropertyType] = useState<PropertyType | "">(initialValues?.propertyType ?? "");
  const [condition, setCondition] = useState<Condition | "">(initialValues?.condition ?? "");
  const [arvError, setArvError] = useState<string | null>(null);

  const priceValue = parseNumeric(price);
  const arvValue = parseNumeric(arv);

  // Live Deal_ARV_Pct: only meaningful while both price > 0 and arv > 0 (13.2).
  // `computeArvPct` returns null for any non-positive/non-finite input, which we
  // render as a suppressed value (13.3).
  const arvPct = useMemo(
    () => computeArvPct(priceValue ?? NaN, arvValue ?? NaN),
    [priceValue, arvValue],
  );

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    // Requirement 13.3: arv empty or 0 suppresses Deal_ARV_Pct and surfaces a
    // validation message; submission does not proceed.
    if (arvValue === null || arvValue <= 0) {
      setArvError("arv must be greater than 0");
      return;
    }
    setArvError(null);

    if (priceValue === null || propertyType === "" || condition === "") {
      // Required structured fields must be present to assemble a PropertyInput.
      return;
    }

    const property: PropertyInput = {
      address,
      city,
      price: priceValue,
      arv: arvValue,
      beds: parseNumeric(beds),
      baths: parseNumeric(baths),
      property_type: propertyType,
      condition,
    };
    onSubmit(property);
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={handleSubmit} noValidate>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Address</span>
          <input
            type="text"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            required
            className="rounded-md border border-gray-300 px-3 py-2"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">City</span>
          <input
            type="text"
            value={city}
            onChange={(e) => setCity(e.target.value)}
            required
            className="rounded-md border border-gray-300 px-3 py-2"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Price</span>
          <input
            type="number"
            inputMode="numeric"
            min={0}
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            required
            className="rounded-md border border-gray-300 px-3 py-2"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">ARV</span>
          <input
            type="number"
            inputMode="numeric"
            min={0}
            value={arv}
            onChange={(e) => {
              setArv(e.target.value);
              // Clear a stale validation message once the user edits ARV.
              if (arvError) {
                setArvError(null);
              }
            }}
            aria-invalid={arvError !== null}
            className="rounded-md border border-gray-300 px-3 py-2"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Beds</span>
          <input
            type="number"
            inputMode="numeric"
            min={0}
            value={beds}
            onChange={(e) => setBeds(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Baths</span>
          <input
            type="number"
            inputMode="decimal"
            min={0}
            step="0.5"
            value={baths}
            onChange={(e) => setBaths(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Property type</span>
          <select
            value={propertyType}
            onChange={(e) => setPropertyType(e.target.value as PropertyType | "")}
            required
            className="rounded-md border border-gray-300 px-3 py-2"
          >
            <option value="" disabled>
              Select…
            </option>
            {PROPERTY_TYPES.map((t) => (
              <option key={t} value={t}>
                {humanizeEnum(t)}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Condition</span>
          <select
            value={condition}
            onChange={(e) => setCondition(e.target.value as Condition | "")}
            required
            className="rounded-md border border-gray-300 px-3 py-2"
          >
            <option value="" disabled>
              Select…
            </option>
            {CONDITIONS.map((c) => (
              <option key={c} value={c}>
                {humanizeEnum(c)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* Live Deal_ARV_Pct (13.2) — suppressed when arv is empty/0 (13.3). */}
      <div className="text-sm" aria-live="polite">
        {arvPct !== null ? (
          <p className="text-gray-700">
            Deal ARV%:{" "}
            <span className="font-semibold" data-testid="deal-arv-pct">
              {arvPct.toFixed(1)}%
            </span>
          </p>
        ) : null}
        {arvError !== null ? (
          <p className="text-amber-700" role="alert">
            {arvError}
          </p>
        ) : null}
      </div>

      <div>
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {submitting ? "Finding…" : submitLabel}
        </button>
      </div>
    </form>
  );
}
