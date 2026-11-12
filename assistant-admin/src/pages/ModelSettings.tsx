import ModelsPage from "./Models";
import LimitsPage from "./Limits";

export default function ModelSettingsPage() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <ModelsPage />
      <LimitsPage />
    </div>
  );
}
