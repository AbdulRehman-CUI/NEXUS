import type { Metadata } from "next";
import { WorkspaceApp } from "../../components/workspace-app";

export const metadata: Metadata = { title: "Models" };

export default function Models() {
  return <WorkspaceApp mode="models" />;
}
