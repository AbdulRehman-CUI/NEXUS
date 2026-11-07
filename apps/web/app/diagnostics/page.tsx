import type { Metadata } from "next";
export const metadata: Metadata = { title: "Diagnostics" };
import { WorkspaceApp } from "../../components/workspace-app";
export default function Page() {
  return <WorkspaceApp mode="diagnostics" />;
}
