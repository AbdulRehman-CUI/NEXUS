import type { Metadata } from "next";
export const metadata: Metadata = { title: "Knowledge Graph" };
import { WorkspaceApp } from "../../components/workspace-app";
export default function Graph() {
  return <WorkspaceApp mode="graph" />;
}
