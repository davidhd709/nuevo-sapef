import { AppShell, Group, Select, Text, Title } from "@mantine/core";

import { EstadoSistema } from "./sistema/EstadoSistema";

export function App() {
  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            <Title order={3}>SAPEF</Title>
            <Text c="dimmed" size="sm">
              Alumbrado público
            </Text>
          </Group>
          {/* El selector de sede se activa con EP-01 (sesión y sedes asignadas). */}
          <Select
            aria-label="Sede"
            data={["Montelíbano", "Alcalá"]}
            placeholder="Sede"
            disabled
            w={180}
          />
        </Group>
      </AppShell.Header>
      <AppShell.Main>
        <EstadoSistema />
      </AppShell.Main>
    </AppShell>
  );
}
