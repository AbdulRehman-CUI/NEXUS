import type { Metadata } from "next";
export const metadata: Metadata = { title: "Models & Privacy" };
import { WorkspaceApp } from "../../components/workspace-app";
export default function Settings() {
  return <WorkspaceApp mode="settings" />;
}
