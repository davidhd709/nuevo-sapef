import { Alert, Button, Card, Center, PasswordInput, Stack, Text, Title } from "@mantine/core";
import { api } from "@sapef/api";
import { useState, type FormEvent } from "react";

import { useAuth } from "./AuthContext";

export function PantallaCambiarClave() {
  const { recargarPerfil, salir } = useAuth();
  const [actual, setActual] = useState("");
  const [nueva, setNueva] = useState("");
  const [confirmacion, setConfirmacion] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function cambiar(e: FormEvent) {
    e.preventDefault();
    if (nueva !== confirmacion) {
      setError("La confirmación no coincide con la nueva contraseña.");
      return;
    }
    setError(null);
    setEnviando(true);
    try {
      const { error: problema, response } = await api.POST("/api/v1/auth/cambiar-clave", {
        body: { clave_actual: actual, clave_nueva: nueva },
      });
      if (!response.ok) {
        setError(
          problema && typeof problema === "object" && "detail" in problema
            ? String(problema.detail)
            : "No se pudo cambiar la contraseña.",
        );
        return;
      }
      await recargarPerfil();
    } catch {
      setError("No se pudo conectar con el servidor. Intenta de nuevo.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <Center mih="100vh" p="md">
      <Card withBorder shadow="sm" p="xl" w={420}>
        <Stack gap="md">
          <Title order={2}>Cambiar contraseña</Title>
          <Text size="sm">Antes de usar SAPEF, define una contraseña propia.</Text>
          {error && <Alert color="red">{error}</Alert>}
          <form onSubmit={(e) => void cambiar(e)}>
            <Stack gap="sm">
              <PasswordInput label="Contraseña temporal" autoComplete="current-password" required value={actual} onChange={(e) => setActual(e.currentTarget.value)} />
              <PasswordInput label="Nueva contraseña" autoComplete="new-password" required value={nueva} onChange={(e) => setNueva(e.currentTarget.value)} description="Mínimo 8 caracteres, con mayúscula, minúscula y número." />
              <PasswordInput label="Confirmar nueva contraseña" autoComplete="new-password" required value={confirmacion} onChange={(e) => setConfirmacion(e.currentTarget.value)} />
              <Button type="submit" loading={enviando} fullWidth>Guardar contraseña</Button>
            </Stack>
          </form>
          <Button variant="subtle" color="gray" onClick={() => void salir()}>Salir</Button>
        </Stack>
      </Card>
    </Center>
  );
}
