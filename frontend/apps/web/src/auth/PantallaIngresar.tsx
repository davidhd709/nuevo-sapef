import {
  Alert,
  Anchor,
  Box,
  Button,
  Center,
  Group,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { IconAlertCircle, IconMailCheck } from "@tabler/icons-react";
import { api } from "@sapef/api";
import { useState, type FormEvent } from "react";

import { MarcaSapef } from "../comun/Marca";
import { useAuth } from "./AuthContext";

export function PantallaIngresar({ onExito }: { onExito: () => void }) {
  const { ingresar } = useAuth();
  const [usuario, setUsuario] = useState("");
  const [clave, setClave] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  const [modoRecuperar, setModoRecuperar] = useState(false);
  const [correoRec, setCorreoRec] = useState("");
  const [mensajeRec, setMensajeRec] = useState<string | null>(null);

  async function manejarSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setEnviando(true);
    try {
      await ingresar(usuario, clave);
      onExito();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error de autenticación");
    } finally {
      setEnviando(false);
    }
  }

  async function manejarRecuperar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMensajeRec(null);
    setEnviando(true);
    try {
      const { data } = await api.POST("/api/v1/auth/recuperar", {
        body: { correo: correoRec },
      });
      setMensajeRec(
        data?.mensaje ??
          "Si el correo está registrado, recibirá instrucciones para restablecer su contraseña.",
      );
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: "var(--sapef-superficie)" }}>
      <Box
        visibleFrom="md"
        style={{
          width: "42%",
          maxWidth: 560,
          background: "var(--sapef-lateral)",
          color: "#e9e8e3",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "40px 48px",
          borderRight: "1px solid var(--sapef-lateral-borde)",
        }}
      >
        <MarcaSapef tinta="#f2f1ec" tamano={24} />
        <div>
          <div style={{ width: 32, height: 3, background: "var(--mantine-color-ambar-5)", marginBottom: 20 }} />
          <Text fz={26} fw={500} lh={1.25} maw={380} c="#f2f1ec">
            Inventario, atención y operación del alumbrado público.
          </Text>
          <Stack gap={10} mt={28}>
            {[
              "Luminarias, hoja de vida y mapa",
              "PQRS y órdenes de trabajo con la app de campo",
              "Materiales y bodega",
              "Análisis comercial de Afinia, Celsia y Vatia",
            ].map((t) => (
              <Group key={t} gap={10} wrap="nowrap">
                <div style={{ width: 6, height: 6, background: "#7b7a74", flex: "none" }} />
                <Text size="sm" c="#b9b8b2">
                  {t}
                </Text>
              </Group>
            ))}
          </Stack>
        </div>
        <Text fz={11} c="#7b7a74" style={{ letterSpacing: "0.08em", textTransform: "uppercase" }}>
          Montelíbano · Alcalá
        </Text>
      </Box>

      <Center style={{ flex: 1 }} p="xl">
        <Stack gap="lg" w="100%" maw={360}>
          <Box hiddenFrom="md" mb="md">
            <MarcaSapef tamano={24} />
          </Box>
          <div>
            <Title order={1}>{modoRecuperar ? "Recuperar contraseña" : "Iniciar sesión"}</Title>
            <Text size="sm" c="dimmed" mt={6}>
              {modoRecuperar
                ? "Escriba el correo de su cuenta y le enviaremos un enlace para crear una nueva contraseña."
                : "Ingrese con el usuario que le asignó el administrador."}
            </Text>
          </div>

          {error && (
            <Alert color="red" icon={<IconAlertCircle size={18} />}>
              {error}
            </Alert>
          )}
          {mensajeRec && (
            <Alert color="blue" icon={<IconMailCheck size={18} />}>
              {mensajeRec}
            </Alert>
          )}

          {!modoRecuperar ? (
            <form onSubmit={manejarSubmit}>
              <Stack gap="md">
                <TextInput
                  label="Usuario o correo"
                  name="usuario"
                  autoComplete="username"
                  required
                  size="md"
                  value={usuario}
                  onChange={(e) => setUsuario(e.currentTarget.value)}
                />
                <PasswordInput
                  label="Contraseña"
                  name="clave"
                  autoComplete="current-password"
                  required
                  size="md"
                  value={clave}
                  onChange={(e) => setClave(e.currentTarget.value)}
                />
                <Button type="submit" loading={enviando} fullWidth size="md" mt={4}>
                  Ingresar
                </Button>
                <Anchor
                  component="button"
                  type="button"
                  size="sm"
                  ta="left"
                  onClick={() => {
                    setModoRecuperar(true);
                    setError(null);
                  }}
                >
                  ¿Olvidó su contraseña?
                </Anchor>
              </Stack>
            </form>
          ) : (
            <form onSubmit={manejarRecuperar}>
              <Stack gap="md">
                <TextInput
                  label="Correo electrónico"
                  name="correo"
                  type="email"
                  required
                  size="md"
                  value={correoRec}
                  onChange={(e) => setCorreoRec(e.currentTarget.value)}
                />
                <Button type="submit" loading={enviando} fullWidth size="md">
                  Enviar instrucciones
                </Button>
                <Anchor
                  component="button"
                  type="button"
                  size="sm"
                  ta="left"
                  onClick={() => {
                    setModoRecuperar(false);
                    setMensajeRec(null);
                  }}
                >
                  Volver a iniciar sesión
                </Anchor>
              </Stack>
            </form>
          )}
        </Stack>
      </Center>
    </div>
  );
}
