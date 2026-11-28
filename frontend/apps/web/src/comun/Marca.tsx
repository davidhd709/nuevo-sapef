// Identidad de SAPEF: un poste con su brazo y el cono de luz de la luminaria, y el nombre en
// monoespaciada. Sin degradados ni efectos: funciona en una sola tinta y a 16 px.
import { Group, Text } from "@mantine/core";

export function SimboloSapef({ tamano = 22, tinta = "currentColor" }: { tamano?: number; tinta?: string }) {
  return (
    <svg width={tamano} height={tamano} viewBox="0 0 24 24" aria-hidden="true" fill="none">
      {/* cono de luz */}
      <path d="M15.2 8.2 L11.4 19.5 H21.6 L17.8 8.2 Z" fill="var(--mantine-color-ambar-5)" opacity="0.9" />
      {/* poste y brazo */}
      <path d="M6 22 V5.5 C6 3.8 7.2 3 8.6 3 H16.5" stroke={tinta} strokeWidth="2" strokeLinecap="square" />
      {/* cabeza de la luminaria */}
      <rect x="14.2" y="5.6" width="4.6" height="2.6" rx="0.6" fill={tinta} />
      <path d="M3.5 22 H9" stroke={tinta} strokeWidth="2" strokeLinecap="square" />
    </svg>
  );
}

export function MarcaSapef({
  tinta = "currentColor",
  subtitulo = true,
  tamano = 22,
}: {
  tinta?: string;
  subtitulo?: boolean;
  tamano?: number;
}) {
  return (
    <Group gap={10} wrap="nowrap" style={{ color: tinta }}>
      <SimboloSapef tamano={tamano} tinta={tinta} />
      <div style={{ lineHeight: 1 }}>
        <Text
          component="span"
          ff="monospace"
          fw={600}
          fz={tamano * 0.72}
          style={{ letterSpacing: "0.14em", display: "block", color: tinta }}
        >
          SAPEF
        </Text>
        {subtitulo && (
          <Text component="span" fz={10} style={{ letterSpacing: "0.06em", opacity: 0.6, display: "block", marginTop: 4 }}>
            Alumbrado público
          </Text>
        )}
      </div>
    </Group>
  );
}
