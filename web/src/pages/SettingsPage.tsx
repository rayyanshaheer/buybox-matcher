/**
 * Settings page for managing user-provided API keys (BYOK).
 *
 * The key is stored in localStorage and sent to the backend as a header
 * on extraction requests. It never leaves the browser otherwise.
 */
import { useState, useEffect } from "react";
import { getStoredApiKey, setStoredApiKey, clearStoredApiKey } from "../lib/api";

export default function SettingsPage() {
  const [apiKey, setApiKey] = useState("");
  const [saved, setSaved] = useState(false);
  const [hasKey, setHasKey] = useState(false);

  useEffect(() => {
    const stored = getStoredApiKey();
    if (stored) {
      setApiKey(stored);
      setHasKey(true);
    }
  }, []);

  function handleSave(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = apiKey.trim();
    if (trimmed) {
      setStoredApiKey(trimmed);
      setHasKey(true);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    }
  }

  function handleClear() {
    clearStoredApiKey();
    setApiKey("");
    setHasKey(false);
    setSaved(false);
  }

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-lg font-medium">Settings</h2>
        <p className="text-sm text-gray-500">
          Provide your own OpenAI API key to use the extraction feature. Your key
          is stored locally in your browser and sent securely to the backend only
          when extracting.
        </p>
      </div>

      <form onSubmit={handleSave} className="space-y-4">
        <div>
          <label
            htmlFor="api-key"
            className="block text-sm font-medium text-gray-700"
          >
            OpenAI API Key
          </label>
          <input
            id="api-key"
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-..."
            className="mt-1 w-full rounded-md border border-gray-300 p-2 text-sm shadow-sm focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-500"
          />
          <p className="mt-1 text-xs text-gray-400">
            Get your key from{" "}
            <a
              href="https://platform.openai.com/api-keys"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-gray-600"
            >
              platform.openai.com/api-keys
            </a>
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={apiKey.trim() === ""}
            className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-400"
          >
            Save Key
          </button>
          {hasKey && (
            <button
              type="button"
              onClick={handleClear}
              className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100"
            >
              Remove Key
            </button>
          )}
        </div>
      </form>

      {saved && (
        <div
          role="status"
          className="rounded-md border border-green-200 bg-green-50 p-3 text-sm text-green-700"
        >
          API key saved. You can now use the Extract feature.
        </div>
      )}

      {hasKey && !saved && (
        <div className="rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-700">
          ✓ API key is configured. Extraction requests will use your key.
        </div>
      )}

      {!hasKey && (
        <div className="rounded-md border border-yellow-200 bg-yellow-50 p-3 text-sm text-yellow-700">
          No API key set. The Extract feature requires an OpenAI API key to work.
        </div>
      )}
    </section>
  );
}
