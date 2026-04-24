import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useAppStore, type SetupTab } from '@/store/useAppStore';
import { ActuatorPanel } from './ActuatorPanel';
import { PageShell } from './PageShell';

export function SetupPage() {
  const tab = useAppStore((s) => s.ui.setupTab);
  const setUi = useAppStore((s) => s.setUi);

  return (
    <PageShell title="Setup">
      <Tabs value={tab} onValueChange={(v) => setUi({ setupTab: v as SetupTab })}>
        <TabsList>
          <TabsTrigger value="axial">Axial</TabsTrigger>
          <TabsTrigger value="horizontal">Horizontal</TabsTrigger>
          <TabsTrigger value="lateral">Lateral</TabsTrigger>
        </TabsList>
        <TabsContent value="axial">
          <ActuatorPanel actuator="axial" />
        </TabsContent>
        <TabsContent value="horizontal">
          <ActuatorPanel actuator="horizontal" />
        </TabsContent>
        <TabsContent value="lateral">
          <ActuatorPanel actuator="lateral" />
        </TabsContent>
      </Tabs>
    </PageShell>
  );
}
