import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource/noto-sans-arabic/400.css";
import "./index.css";
import "./styles/brand.css";
import "./styles/workspace.css";
import "./styles/canopus.css";
import App from "./App";
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
