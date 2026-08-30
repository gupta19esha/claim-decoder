import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

// Self-hosted rather than fetched from a third party: this is opened on a
// phone in a hospital corridor and every round trip costs.
//
// Latin only. The variable packages ship one stylesheet covering Cyrillic,
// Greek and Latin Extended, which is ~200 KB of glyphs an English-language
// Indian product will never render. The @font-face rules below are declared
// directly against the latin .woff2 files so only those ship.
import "./fonts.css";

import "./theme.css";
// Superseded screen styles, imported after the theme so they keep winning
// until each screen is rebuilt.
import "./styles/index.css";

import Landing from "./routes/Landing.jsx";
import Rejection from "./routes/Rejection.jsx";
import { BillRoute } from "./App.jsx";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/rejection" element={<Rejection />} />
        <Route path="/bill" element={<BillRoute />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
