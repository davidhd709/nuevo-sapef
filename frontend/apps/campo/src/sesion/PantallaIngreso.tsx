import { Alert, Button, Card, PasswordInput, Stack, Text, TextInput, Title } from "@mantine/core";
import { useState, type FormEvent } from "react";

import { useEnLinea } from "../comun/ganchos";

export function PantallaIngreso({
  onIngresar,
  aviso,
}: {
  onIngresar: (usuario: string, clave: string) => Promise<void>;
  aviso?: string;
}) {
  const enLinea = useEnLinea();
  const [usuario, setUsuario] = useState("");
  const [clave, setClave] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  const enviar = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setEnviando(true);
    try {
      await onIngresar(usuario.trim(), clave);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar sesión.");
    } finally {
      setEnviando(false);
    }
  };

  return (
    <Stack maw={420} mx="auto" mt="xl" px="md">
      <div>
        <Title order={2}>SAPEF Campo</Title>
        <Text c="dimmed" size="sm">
          Órdenes de trabajo de alumbrado público, con o sin señal.
        </Text>
      </div>
      {aviso && <Alert color="yellow">{aviso}</Alert>}
      {!enLinea && (
        <Alert color="gray">Sin señal. Para ingresar la primera vez se necesita conexión.</Alert>
      )}
      <Card withBorder padding="lg">
        <form onSubmit={(e) => void enviar(e)}>
          <Stack>
            <TextInput
              name="usuario"
              label="Usuario"
              autoComplete="username"
              autoCapitalize="none"
              required
              value={usuario}
              onChange={(e) => setUsuario(e.currentTarget.value)}
            />
            <PasswordInput
              name="clave"
              label="Contraseña"
              autoComplete="current-password"
              required
              value={clave}
              onChange={(e) => setClave(e.currentTarget.value)}
            />
            {error && (
              <Text c="red" size="sm">
                {error}
              </Text>
            )}
            <Button type="submit" loading={enviando} fullWidth>
              Ingresar
            </Button>
          </Stack>
        </form>
      </Card>
    </Stack>
  );
}

export function PantallaCambiarClave({
  onCambiar,
  onSalir,
}: {
  onCambiar: (actual: string, nueva: string) => Promise<void>;
  onSalir: () => void;
}) {
  const [actual, setActual] = useState("");
  const [nueva, setNueva] = useState("");
  const [confirmacion, setConfirmacion] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  const enviar = async (e: FormEvent) => {
    e.preventDefault();
    if (nueva !== confirmacion) {
      setError("La confirmación no coincide.");
      return;
    }
    setError(null);
    setEnviando(true);
    try {
      await onCambiar(actual, nueva);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cambiar la contraseña.");
    } finally {
      setEnviando(false);
    }
  };

  return (
    <Stack maw={420} mx="auto" mt="xl" px="md">
      <Title order={3}>Cambie su contraseña</Title>
      <Text size="sm" c="dimmed">
        Es su primer ingreso o la contraseña fue restablecida.
      </Text>
      <Card withBorder padding="lg">
        <form onSubmit={(e) => void enviar(e)}>
          <Stack>
            <PasswordInput
              name="clave_actual"
              label="Contraseña actual"
              required
              value={actual}
              onChange={(e) => setActual(e.currentTarget.value)}
            />
            <PasswordInput
              name="clave_nueva"
              label="Contraseña nueva"
              required
              value={nueva}
              onChange={(e) => setNueva(e.currentTarget.value)}
            />
            <PasswordInput
              name="clave_confirmacion"
              label="Repita la contraseña nueva"
              required
              value={confirmacion}
              onChange={(e) => setConfirmacion(e.currentTarget.value)}
            />
            {error && (
              <Text c="red" size="sm">
                {error}
              </Text>
            )}
            <Button type="submit" loading={enviando} fullWidth>
              Cambiar contraseña
            </Button>
            <Button variant="subtle" onClick={onSalir}>
              Salir
            </Button>
          </Stack>
        </form>
      </Card>
    </Stack>
  );
}
