// Sistema visual de SAPEF: «operativo sobrio».
// Herramienta de trabajo densa: neutros grafito, un solo acento ámbar (la luz de sodio del
// alumbrado) reservado para la acción principal y lo activo, bordes finos en vez de sombras,
// radios pequeños, IBM Plex Sans para el texto y Plex Mono para códigos y cifras.
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  createTheme,
  defaultVariantColorsResolver,
  Drawer,
  Menu,
  Modal,
  Pagination,
  Paper,
  Table,
  Tabs,
  Tooltip,
  type MantineColorsTuple,
  type VariantColorsResolver,
} from "@mantine/core";

// Ámbar de sodio. [5] es el acento; [7]-[8] sirven para texto sobre fondo claro (contraste AA).
const ambar: MantineColorsTuple = [
  "#fdf7ec",
  "#f9ebcf",
  "#f3d6a0",
  "#edc06e",
  "#e9ae4c",
  "#e8a33d",
  "#d18f2a",
  "#a06a18",
  "#7a5012",
  "#54380f",
];

// Grafito: neutros con un leve tono cálido que acompaña al ámbar.
const grafito: MantineColorsTuple = [
  "#f7f7f5",
  "#efefec",
  "#e3e3df",
  "#cfcfca",
  "#a9a9a3",
  "#84847e",
  "#63635e",
  "#474743",
  "#2e2e2b",
  "#1c1c1a",
];

// Superficies del modo oscuro (Mantine usa dark[7] de fondo, dark[6] para paneles y dark[0] para texto).
const oscuro: MantineColorsTuple = [
  "#e6e5e1",
  "#c4c3be",
  "#9c9b95",
  "#73726c",
  "#4d4c47",
  "#3a3935",
  "#2a2926",
  "#1f1e1c",
  "#181715",
  "#100f0e",
];

// El ámbar es solo para la acción principal (variante «filled») y lo activo. Las variantes suaves
// («light», «outline») sin color explícito salen neutras: un botón secundario o una etiqueta sin
// significado no deben competir con la acción principal.
const resolverVariantes: VariantColorsResolver = (entrada) => {
  const base = defaultVariantColorsResolver(entrada);
  const esPrimario = !entrada.color || entrada.color === "ambar";
  if (esPrimario && (entrada.variant === "light" || entrada.variant === "outline")) {
    return {
      background: "var(--mantine-color-default)",
      hover: "var(--mantine-color-default-hover)",
      color: "var(--mantine-color-default-color)",
      border: "1px solid var(--mantine-color-default-border)",
    };
  }
  return base;
};

export const tema = createTheme({
  variantColorResolver: resolverVariantes,
  colors: { ambar, gray: grafito, dark: oscuro },
  primaryColor: "ambar",
  primaryShade: { light: 5, dark: 5 },
  // Texto oscuro sobre el ámbar: blanco sobre #e8a33d no llega al contraste mínimo.
  autoContrast: true,
  luminanceThreshold: 0.3,
  white: "#ffffff",
  black: "#1c1c1a",

  fontFamily: "'IBM Plex Sans', system-ui, sans-serif",
  fontFamilyMonospace: "'IBM Plex Mono', ui-monospace, monospace",
  headings: {
    fontFamily: "'IBM Plex Sans', system-ui, sans-serif",
    fontWeight: "600",
    sizes: {
      h1: { fontSize: "1.5rem", lineHeight: "1.25" },
      h2: { fontSize: "1.25rem", lineHeight: "1.3" },
      h3: { fontSize: "1.0625rem", lineHeight: "1.35" },
      h4: { fontSize: "0.9375rem", lineHeight: "1.4" },
      h5: { fontSize: "0.875rem", lineHeight: "1.4" },
      h6: { fontSize: "0.75rem", lineHeight: "1.4" },
    },
  },
  fontSizes: { xs: "0.75rem", sm: "0.8125rem", md: "0.875rem", lg: "1rem", xl: "1.125rem" },
  lineHeights: { xs: "1.4", sm: "1.45", md: "1.5", lg: "1.5", xl: "1.5" },
  radius: { xs: "2px", sm: "4px", md: "6px", lg: "8px", xl: "10px" },
  defaultRadius: "sm",
  spacing: { xs: "0.5rem", sm: "0.75rem", md: "1rem", lg: "1.5rem", xl: "2rem" },
  shadows: {
    xs: "0 1px 2px rgba(28,28,26,0.06)",
    sm: "0 1px 3px rgba(28,28,26,0.08)",
    md: "0 4px 12px rgba(28,28,26,0.10)",
    lg: "0 8px 24px rgba(28,28,26,0.12)",
    xl: "0 16px 40px rgba(28,28,26,0.14)",
  },
  cursorType: "pointer",
  focusRing: "auto",

  components: {
    Button: Button.extend({
      defaultProps: { size: "sm", radius: "sm" },
      styles: { root: { fontWeight: 500 } },
    }),
    Badge: Badge.extend({
      defaultProps: { variant: "light", radius: "sm", size: "md" },
      styles: { root: { textTransform: "none", fontWeight: 500, letterSpacing: 0 } },
    }),
    Card: Card.extend({ defaultProps: { withBorder: true, radius: "sm", shadow: "none", padding: "md" } }),
    Paper: Paper.extend({ defaultProps: { radius: "sm", shadow: "none" } }),
    Table: Table.extend({
      defaultProps: { verticalSpacing: 7, horizontalSpacing: "sm", highlightOnHover: true, striped: false },
    }),
    Tabs: Tabs.extend({ defaultProps: { color: "ambar" } }),
    Anchor: Anchor.extend({ defaultProps: { c: "ambar.8", underline: "hover" } }),
    Alert: Alert.extend({ defaultProps: { variant: "light", radius: "sm" } }),
    Modal: Modal.extend({
      defaultProps: { radius: "md", overlayProps: { backgroundOpacity: 0.4, blur: 0 }, padding: "lg" },
    }),
    Drawer: Drawer.extend({ defaultProps: { overlayProps: { backgroundOpacity: 0.3, blur: 0 } } }),
    Menu: Menu.extend({ defaultProps: { radius: "sm", shadow: "md" } }),
    Pagination: Pagination.extend({ defaultProps: { size: "sm", radius: "sm" } }),
    Tooltip: Tooltip.extend({ defaultProps: { radius: "sm", openDelay: 300 } }),
  },
});
