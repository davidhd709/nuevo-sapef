import "@mantine/core/styles.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./estilos.css";

import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { tema } from "./tema";

const consultas = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

const raiz = document.getElementById("raiz");
if (!raiz) throw new Error("No se encontró el elemento #raiz");

createRoot(raiz).render(
  <StrictMode>
    <MantineProvider theme={tema} defaultColorScheme="light">
      <QueryClientProvider client={consultas}>
        <App />
      </QueryClientProvider>
    </MantineProvider>
  </StrictMode>,
);
