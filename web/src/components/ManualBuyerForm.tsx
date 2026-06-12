/**
 * Manual buyer entry form — add a buyer with structured buy box criteria
 * without needing AI or an API key.
 */
import { useState, type FormEvent } from "react";

interface ManualBuyerFormProps {
  onSubmit: (data: ManualBuyerData) => void;
  submitting?: boolean;
}

export interface ManualBuyerData {
  name: string;
  company: string | null;
  markets: string[];
  strategy: string | null;
  property_type: string | null;
  price_min: number | null;
  price_max: number | null;
  arv_pct_max: number | null;
  min_beds: number | null;
  min_baths: number | null;
  condition: string | null;
}

const STRATEGIES = ["fix_and_flip", "buy_and_hold", "brrrr", "wholesale"];
const PROPERTY_TYPES = ["single_family", "multi_family", "condo", "land"];
const CONDITIONS = ["distressed", "light_rehab", "turnkey", "any"];

function humanize(value: string): string {
  const spaced = value.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export default function ManualBuyerForm({
  onSubmit,
  submitting = false,
}: ManualBuyerFormProps) {
  const [name, setName] = useState("");
  const [company, setCompany] = useState("");
  const [markets, setMarkets] = useState("");
  const [strategy, setStrategy] = useState("");
  const [propertyType, setPropertyType] = useState("");
  const [priceMin, setPriceMin] = useState("");
  const [priceMax, setPriceMax] = useState("");
  const [arvPctMax, setArvPctMax] = useState("");
  const [minBeds, setMinBeds] = useState("");
  const [minBaths, setMinBaths] = useState("");
  const [condition, setCondition] = useState("");
  const [error, setError] = useState<string | null>(null);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (!name.trim()) {
      setError("Buyer name is required.");
      return;
    }

    const parsedMarkets = markets
      .split(",")
      .map((m) => m.trim())
      .filter((m) => m.length > 0);

    const pMin = priceMin ? parseInt(priceMin) : null;
    const pMax = priceMax ? parseInt(priceMax) : null;

    if (pMin !== null && pMax !== null && pMin > pMax) {
      setError("Price min cannot be greater than price max.");
      return;
    }

    const data: ManualBuyerData = {
      name: name.trim(),
      company: company.trim() || null,
      markets: parsedMarkets,
      strategy: strategy || null,
      property_type: propertyType || null,
      price_min: pMin,
      price_max: pMax,
      arv_pct_max: arvPctMax ? parseInt(arvPctMax) : null,
      min_beds: minBeds ? parseInt(minBeds) : null,
      min_baths: minBaths ? parseFloat(minBaths) : null,
      condition: condition || null,
    };

    onSubmit(data);
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={handleSubmit} noValidate>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Buyer name *</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. John Smith"
            disabled={submitting}
            className="rounded-md border border-gray-300 px-3 py-2"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Company</span>
          <input
            type="text"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            placeholder="e.g. Smith Capital LLC"
            disabled={submitting}
            className="rounded-md border border-gray-300 px-3 py-2"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm sm:col-span-2">
          <span className="font-medium text-gray-700">Markets</span>
          <input
            type="text"
            value={markets}
            onChange={(e) => setMarkets(e.target.value)}
            placeholder="Comma-separated cities, e.g. Tampa, Orlando, Lakeland"
            disabled={submitting}
            className="rounded-md border border-gray-300 px-3 py-2"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Strategy</span>
          <select
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
            disabled={submitting}
            className="rounded-md border border-gray-300 px-3 py-2"
          >
            <option value="">Not specified</option>
            {STRATEGIES.map((s) => (
              <option key={s} value={s}>{humanize(s)}</option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Property type</span>
          <select
            value={propertyType}
            onChange={(e) => setPropertyType(e.target.value)}
            disabled={submitting}
            className="rounded-md border border-gray-300 px-3 py-2"
          >
            <option value="">Not specified</option>
            {PROPERTY_TYPES.map((t) => (
              <option key={t} value={t}>{humanize(t)}</option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Price min ($)</span>
          <input
            type="number"
            value={priceMin}
            onChange={(e) => setPriceMin(e.target.value)}
            placeholder="e.g. 100000"
            disabled={submitting}
            className="rounded-md border border-gray-300 px-3 py-2"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Price max ($)</span>
          <input
            type="number"
            value={priceMax}
            onChange={(e) => setPriceMax(e.target.value)}
            placeholder="e.g. 300000"
            disabled={submitting}
            className="rounded-md border border-gray-300 px-3 py-2"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Max ARV %</span>
          <input
            type="number"
            min={0}
            max={100}
            value={arvPctMax}
            onChange={(e) => setArvPctMax(e.target.value)}
            placeholder="e.g. 70"
            disabled={submitting}
            className="rounded-md border border-gray-300 px-3 py-2"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Condition</span>
          <select
            value={condition}
            onChange={(e) => setCondition(e.target.value)}
            disabled={submitting}
            className="rounded-md border border-gray-300 px-3 py-2"
          >
            <option value="">Not specified</option>
            {CONDITIONS.map((c) => (
              <option key={c} value={c}>{humanize(c)}</option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Min beds</span>
          <input
            type="number"
            min={0}
            value={minBeds}
            onChange={(e) => setMinBeds(e.target.value)}
            placeholder="e.g. 3"
            disabled={submitting}
            className="rounded-md border border-gray-300 px-3 py-2"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Min baths</span>
          <input
            type="number"
            min={0}
            step="0.5"
            value={minBaths}
            onChange={(e) => setMinBaths(e.target.value)}
            placeholder="e.g. 2"
            disabled={submitting}
            className="rounded-md border border-gray-300 px-3 py-2"
          />
        </label>
      </div>

      {error && (
        <p className="text-sm text-red-600" role="alert">{error}</p>
      )}

      <div>
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50"
        >
          {submitting ? "Saving…" : "Save Buyer"}
        </button>
      </div>
    </form>
  );
}
