import "@mantine/core/styles.css";

import { createTheme, MantineProvider } from "@mantine/core";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { registrarServiceWorker } from "./datos/actualizacion";

// Botones y textos grandes: se usa con guantes, al sol y con una mano.
const tema = createTheme({
  primaryColor: "yellow",
  defaultRadius: "md",
  fontFamily: "'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif",
});

registrarServiceWorker();

const raiz = document.getElementById("raiz");
if (!raiz) throw new Error("No se encontró el elemento #raiz");

createRoot(raiz).render(
  <StrictMode>
    <MantineProvider theme={tema} defaultColorScheme="light">
      <App />
    </MantineProvider>
  </StrictMode>,
);
