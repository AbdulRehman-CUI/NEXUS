import type { Metadata } from "next";
export const metadata: Metadata = { title: "Obsidian Vaults" };
import { WorkspaceApp } from "../../components/workspace-app";
export default function Vaults() {
  return <WorkspaceApp mode="vaults" />;
}
