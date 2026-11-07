import type { Metadata } from "next";
export const metadata: Metadata = { title: "Knowledge Library" };
import { WorkspaceApp } from "../../components/workspace-app";
export default function Library() {
  return <WorkspaceApp mode="library" />;
}
