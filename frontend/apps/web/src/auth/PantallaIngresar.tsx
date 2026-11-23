import {
  Alert,
  Anchor,
  Button,
  Card,
  Center,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { api } from "@sapef/api";
import { useState, type FormEvent } from "react";

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
    <Center mih="80vh">
      <Card withBorder shadow="sm" p="xl" w={400}>
        <Stack gap="md">
          <div>
            <Title order={2}>SAPEF</Title>
            <Text size="sm" c="dimmed">
              Sistema de gestión de alumbrado público
            </Text>
          </div>

          {error && (
            <Alert color="red" title="Error">
              {error}
            </Alert>
          )}
          {mensajeRec && (
            <Alert color="blue" title="Recuperación">
              {mensajeRec}
            </Alert>
          )}

          {!modoRecuperar ? (
            <form onSubmit={manejarSubmit}>
              <Stack gap="sm">
                <TextInput
                  label="Usuario o correo"
                  name="usuario"
                  autoComplete="username"
                  required
                  value={usuario}
                  onChange={(e) => setUsuario(e.currentTarget.value)}
                />
                <PasswordInput
                  label="Contraseña"
                  name="clave"
                  autoComplete="current-password"
                  required
                  value={clave}
                  onChange={(e) => setClave(e.currentTarget.value)}
                />
                <Button type="submit" loading={enviando} fullWidth mt="xs">
                  Ingresar
                </Button>
                <Anchor
                  component="button"
                  type="button"
                  size="sm"
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
              <Stack gap="sm">
                <TextInput
                  label="Correo electrónico"
                  name="correo"
                  type="email"
                  required
                  value={correoRec}
                  onChange={(e) => setCorreoRec(e.currentTarget.value)}
                />
                <Button type="submit" loading={enviando} fullWidth>
                  Enviar instrucciones
                </Button>
                <Anchor
                  component="button"
                  type="button"
                  size="sm"
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
      </Card>
    </Center>
  );
}
