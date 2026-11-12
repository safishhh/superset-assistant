import { Tabs } from "antd";
import UsagePage from "./Usage";
import RankingsPage from "./Rankings";

export default function UsageStatsPage() {
  return (
    <Tabs
      size="small"
      items={[
        { key: "usage", label: "用量", children: <UsagePage /> },
        { key: "rankings", label: "榜单", children: <RankingsPage /> },
      ]}
    />
  );
}
