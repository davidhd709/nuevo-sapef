import { Alert, Box, Button, Center, PasswordInput, Stack, Text, Title } from "@mantine/core";
import { api } from "@sapef/api";
import { useState, type FormEvent } from "react";

import { MarcaSapef } from "../comun/Marca";
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
    <Center mih="100vh" p="xl" style={{ background: "var(--sapef-superficie)" }}>
      <Box w="100%" maw={380}>
        <Stack gap="lg">
          <MarcaSapef tamano={24} />
          <div>
            <Title order={1}>Cree su contraseña</Title>
            <Text size="sm" c="dimmed" mt={6}>
              Antes de usar SAPEF, cambie la contraseña temporal por una propia.
            </Text>
          </div>
          {error && <Alert color="red">{error}</Alert>}
          <form onSubmit={(e) => void cambiar(e)}>
            <Stack gap="sm">
              <PasswordInput label="Contraseña temporal" autoComplete="current-password" required value={actual} onChange={(e) => setActual(e.currentTarget.value)} />
              <PasswordInput label="Nueva contraseña" autoComplete="new-password" required value={nueva} onChange={(e) => setNueva(e.currentTarget.value)} description="Mínimo 8 caracteres, con mayúscula, minúscula y número." />
              <PasswordInput label="Confirmar nueva contraseña" autoComplete="new-password" required value={confirmacion} onChange={(e) => setConfirmacion(e.currentTarget.value)} />
              <Button type="submit" loading={enviando} fullWidth size="md" mt={4}>Guardar contraseña</Button>
            </Stack>
          </form>
          <Button variant="subtle" color="gray" onClick={() => void salir()}>Cerrar sesión</Button>
        </Stack>
      </Box>
    </Center>
  );
}
