import { BrowserRouter, NavLink, Navigate, Route, Routes } from "react-router-dom";
import ExtractPage from "./pages/ExtractPage";
import MatchPage from "./pages/MatchPage";

/**
 * Application shell and router.
 *
 * Exposes the two product routes from the design's "Frontend Module
 * Responsibilities" table:
 *  - `/extract` -> Extract_Screen (ExtractPage)
 *  - `/match`   -> Match_Screen (MatchPage)
 *
 * `/` redirects to `/match`. Unknown paths fall back to `/match` as well.
 */
const navLinkClass = ({ isActive }: { isActive: boolean }): string =>
  `rounded px-3 py-1.5 text-sm font-medium ${
    isActive ? "bg-gray-900 text-white" : "text-gray-700 hover:bg-gray-200"
  }`;

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-50 text-gray-900">
        <header className="border-b border-gray-200 bg-white">
          <div className="mx-auto flex max-w-3xl items-center justify-between p-4">
            <h1 className="text-xl font-semibold">BuyBox Matcher</h1>
            <nav className="flex gap-2">
              <NavLink to="/extract" className={navLinkClass}>
                Extract
              </NavLink>
              <NavLink to="/match" className={navLinkClass}>
                Match
              </NavLink>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-3xl p-6">
          <Routes>
            <Route path="/" element={<Navigate to="/match" replace />} />
            <Route path="/extract" element={<ExtractPage />} />
            <Route path="/match" element={<MatchPage />} />
            <Route path="*" element={<Navigate to="/match" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
